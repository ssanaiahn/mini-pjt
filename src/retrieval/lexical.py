"""[retrieval] 글자 유사도(bigram) 검색: LLM을 쓸 수 없을 때의 3차 판정과 비교 기준."""
from ..shared.text import similarity

SIMILARITY_THRESHOLD = 0.5   # 3차 판정: 최유사 과거 VOC가 이 값 이상이면 그 메뉴를 차용
HISTORY_THRESHOLD = 0.2      # 유사 VOC 처리 이력(담당자 참고용)의 글자 유사도 기준


def bigram_candidates(conn, voc_text, k=3):
    """메뉴명으로 처리된 과거 VOC를 글자 유사도 높은 순(동점이면 최근 건)으로 k건."""
    rows = conn.execute(
        "SELECT id, voc_text, matched_menus FROM voc_history WHERE is_processable=1"
        " AND COALESCE(match_source, 'menu')='menu' ORDER BY id DESC").fetchall()
    scored = sorted(((similarity(voc_text, r["voc_text"]), r) for r in rows),
                    key=lambda x: (-x[0], -x[1]["id"]))
    return [{"id": r["id"], "voc_text": r["voc_text"],
             "menus": [m for m in r["matched_menus"].split("|") if m],
             "similarity": round(s, 2), "score": s} for s, r in scored[:k]]


def find_similar_voc(conn, voc_text, threshold=SIMILARITY_THRESHOLD):
    """글자 유사도가 기준 이상인 가장 유사한 과거 VOC(메뉴명 판정 건만). 없으면 None.

    유사·에이전트 판정으로 처리된 건은 기준에서 제외해 판정이 번지는 것을 막는다.
    """
    top = bigram_candidates(conn, voc_text, k=1)
    if top and top[0]["score"] >= threshold:
        return {k: v for k, v in top[0].items() if k != "score"}
    return None


def bigram_scorer(query, texts):
    """글자 2개 묶음 자카드 유사도 목록(유사 VOC 처리 이력의 대체 scorer)."""
    return [similarity(query, t) for t in texts]


bigram_scorer.threshold = HISTORY_THRESHOLD
