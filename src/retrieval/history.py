"""[retrieval] 유사 VOC 처리 이력: 같은 메뉴로 접수된 비슷한 과거 VOC와 그 처리 내용(담당자 참고용)."""
from .lexical import HISTORY_THRESHOLD, bigram_scorer

HISTORY_K = 5


def find_similar_history(conn, voc_text, menus, exclude_id=None, registrant_id=None,
                         k=HISTORY_K, scorer=None):
    """같은 메뉴로 접수된 과거 VOC 중 내용이 비슷한 건(처리 내용 포함), 유사도 높은 순 최대 k건.

    판정 근거가 아니라 담당자 참고용이므로 판정 방식(menu/agent/similar)과 관계없이 처리 가능 건을 본다.
    scorer(query, texts) -> [0~1]가 실패하면 글자 유사도로 대체한다.
    """
    menus = set(menus or [])
    if not menus:
        return []
    rows = [r for r in conn.execute(
        "SELECT id, registrant_id, voc_text, matched_menus, created_at, handling_note, handled_at"
        " FROM voc_history WHERE is_processable=1 AND id IS NOT ? ORDER BY id DESC",
        (exclude_id,)) if menus & set(r["matched_menus"].split("|"))]
    if not rows:
        return []
    scorer = scorer or bigram_scorer
    texts = [r["voc_text"] for r in rows]
    try:
        scores = scorer(voc_text, texts)
        threshold = getattr(scorer, "threshold", HISTORY_THRESHOLD)
    except Exception:  # 임베딩 오류·한도 → 글자 유사도
        scores, threshold = bigram_scorer(voc_text, texts), HISTORY_THRESHOLD
    ranked = sorted(zip(scores, rows), key=lambda x: (-x[0], -x[1]["id"]))
    return [{"id": r["id"], "created_at": r["created_at"], "registrant_id": r["registrant_id"],
             "voc_text": r["voc_text"], "menus": [m for m in r["matched_menus"].split("|") if m],
             "handling_note": r["handling_note"], "handled_at": r["handled_at"],
             "similarity": round(s, 2), "same_registrant": r["registrant_id"] == registrant_id}
            for s, r in ranked[:k] if s >= threshold]
