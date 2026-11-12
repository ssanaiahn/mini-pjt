"""과거 VOC 의미 검색: Titan 임베딩 + Chroma(파일 저장).

검색 기준은 '메뉴명으로 처리 가능 판정된' 과거 VOC만이다(유사·에이전트 판정 건은 제외해
판정이 번지는 것을 막는다). SQLite 이력이 원본이고, Chroma는 검색할 때마다 이력과 동기화한다.
"""
import os
from pathlib import Path

from . import llm

COLLECTION = "voc_history"
DEFAULT_PATH = llm.ROOT / "data" / "chroma"


def reference_rows(conn):
    return conn.execute(
        "SELECT id, voc_text, matched_menus FROM voc_history WHERE is_processable=1"
        " AND COALESCE(match_source, 'menu')='menu' ORDER BY id").fetchall()


def _store(path=None):
    from langchain_chroma import Chroma

    path = Path(path or os.environ.get("VOC_CHROMA_PATH") or DEFAULT_PATH)
    path.mkdir(parents=True, exist_ok=True)
    return Chroma(collection_name=COLLECTION, embedding_function=llm.embeddings(),
                  persist_directory=str(path), collection_metadata={"hnsw:space": "cosine"})


def sync(store, rows):
    """이력과 Chroma를 맞춘다: 없어진·내용이 바뀐 건 삭제, 새 건 추가."""
    want = {str(r["id"]): r for r in rows}
    have = store.get(include=["metadatas"])
    stale = [i for i, m in zip(have["ids"], have["metadatas"])
             if i not in want or (m or {}).get("voc_text") != want[i]["voc_text"]]
    if stale:
        store.delete(ids=stale)
    present = set(have["ids"]) - set(stale)
    new = [r for i, r in want.items() if i not in present]
    if new:
        store.add_texts(
            texts=[r["voc_text"] for r in new],
            metadatas=[{"voc_id": r["id"], "voc_text": r["voc_text"],
                        "menus": r["matched_menus"]} for r in new],
            ids=[str(r["id"]) for r in new])


EMBED_CACHE_MAX = 5000  # 앱 프로세스가 켜져 있는 동안 기억할 문장 수(넘으면 오래된 것부터 버림)
_EMBED_CACHE = {}  # 문장 → 임베딩. 과거 VOC 문장은 바뀌지 않으므로 다시 계산하지 않는다


def clear_embedding_cache():
    _EMBED_CACHE.clear()


def _remember(text, vec):
    _EMBED_CACHE[text] = vec
    while len(_EMBED_CACHE) > EMBED_CACHE_MAX:
        _EMBED_CACHE.pop(next(iter(_EMBED_CACHE)))


def _embed(query, texts):
    """질문·문장 임베딩. 캐시에 없는 것만 Titan으로 계산한다."""
    emb = None
    if query not in _EMBED_CACHE:
        emb = llm.embeddings()
        _remember(query, emb.embed_query(query))
    q = _EMBED_CACHE[query]
    missing = list(dict.fromkeys(t for t in texts if t not in _EMBED_CACHE))
    if missing:
        emb = emb or llm.embeddings()
        for t, v in zip(missing, emb.embed_documents(missing)):
            _remember(t, v)
    # 상한을 넘어 방금 버려진 문장이 있으면 그 자리에서 다시 계산
    lost = [t for t in texts if t not in _EMBED_CACHE]
    extra = dict(zip(lost, (emb or llm.embeddings()).embed_documents(lost))) if lost else {}
    return q, [_EMBED_CACHE.get(t) or extra[t] for t in texts]


def embedding_scorer(query, texts):
    """Titan 임베딩 코사인 유사도 목록(유사 VOC 처리 이력용). 오류는 호출한 쪽이 글자 유사도로 대체."""
    import math

    q, docs = _embed(query, list(texts))

    def cos(a, b):
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0
    return [cos(q, d) for d in docs]


# 같은 메뉴 후보만 비교하므로 0.3: 실제 이력에서 같은 요청의 다른 표현은 0.31~0.6,
# 같은 메뉴의 다른 요청(양식 변경 등)은 0.28, 다른 메뉴·잡담은 0.22 이하였다(2026-11-12 확인).
embedding_scorer.threshold = 0.3


SEMANTIC_WEIGHT = 0.7  # 하이브리드 점수 = 0.7 × 의미 유사도 + 0.3 × 글자 유사도
LEXICAL_WEIGHT = 0.3
CANDIDATE_FACTOR = 2   # 의미 검색으로 k의 2배 후보를 가져와 하이브리드 점수로 다시 정렬


def search(conn, voc_text, k=3, path=None):
    """하이브리드 검색: 의미(Titan+Chroma) 후보를 글자 유사도와 섞어 리랭킹한 상위 k건.

    반환 [{id, voc_text, menus, similarity(하이브리드), semantic(1-코사인 거리), lexical(bigram)}]
    """
    from .service import similarity as lexical_similarity

    rows = reference_rows(conn)
    if not rows:
        return []
    store = _store(path)
    sync(store, rows)
    hits = store.similarity_search_with_score(voc_text, k=min(k * CANDIDATE_FACTOR, len(rows)))
    scored = []
    for d, dist in hits:
        sem = 1 - dist
        lex = lexical_similarity(voc_text, d.metadata["voc_text"])
        scored.append((SEMANTIC_WEIGHT * sem + LEXICAL_WEIGHT * lex, sem, lex, d.metadata))
    scored.sort(key=lambda x: -x[0])
    return [{"id": m["voc_id"], "voc_text": m["voc_text"],
             "menus": [x for x in m["menus"].split("|") if x],
             "similarity": round(score, 2), "semantic": round(sem, 2), "lexical": round(lex, 2)}
            for score, sem, lex, m in scored[:k]]
