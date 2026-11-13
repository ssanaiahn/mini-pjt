"""[records] VOC 이력 저장과 메뉴별 누적 계산."""
from datetime import datetime, timezone

FREQUENT_THRESHOLD = 3  # 누적(등록자 무관) 이 값 이상이면 자주 들어오는 VOC


def save_voc(conn, registrant_id, voc_text, matched, guidance, source, match_source,
             similar=None, judge_reason=None):
    """이력 저장 + 처리 가능 건의 메뉴 매칭 기록. (voc_id, created_at)."""
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        "INSERT INTO voc_history(registrant_id, voc_text, is_processable, matched_menus,"
        " guidance_draft, guidance_source, created_at, match_source, similar_voc_id,"
        " similarity, judge_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (registrant_id, voc_text, int(bool(matched)), "|".join(matched), guidance, source,
         created_at, match_source, similar and similar["id"],
         similar and similar["similarity"], judge_reason))
    conn.executemany("INSERT INTO voc_menu_matches(voc_id, menu) VALUES (?,?)",
                     [(cur.lastrowid, m) for m in matched])
    conn.commit()
    return cur.lastrowid, created_at


def get_menu_counts(conn):
    """메뉴별 누적: voc_menu_matches(이력)에서 계산."""
    return {r["menu"]: r["count"] for r in conn.execute(
        "SELECT menu, COUNT(*) AS count FROM voc_menu_matches GROUP BY menu")}
