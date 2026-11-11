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


def search(conn, voc_text, k=3, path=None):
    """의미가 가까운 과거 VOC 상위 k건: [{id, voc_text, menus, similarity}] (similarity = 1 - 코사인 거리)."""
    rows = reference_rows(conn)
    if not rows:
        return []
    store = _store(path)
    sync(store, rows)
    hits = store.similarity_search_with_score(voc_text, k=min(k, len(rows)))
    return [{"id": d.metadata["voc_id"], "voc_text": d.metadata["voc_text"],
             "menus": [m for m in d.metadata["menus"].split("|") if m],
             "similarity": round(1 - dist, 2)} for d, dist in hits]
