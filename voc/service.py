"""VOC 판정·저장·누적·모의 DB 조회."""
from .db import load_menus
from .guidance import generate_guidance

FREQUENT_THRESHOLD = 3


def match_menus(voc_text, menus):
    """본문에 메뉴명 또는 별칭이 부분 문자열로 있으면 매칭(설정 순서 유지)."""
    return [m["name"] for m in menus
            if any(t in voc_text for t in [m["name"], *m.get("aliases", [])])]


def process_voc(conn, voc_text, registrant_id, menus=None, use_api=True):
    voc_text = (voc_text or "").strip()
    registrant_id = (registrant_id or "").strip()
    if not voc_text or not registrant_id:
        return {"error": "VOC 본문과 등록자 ID를 모두 입력하세요."}
    menus = menus or load_menus()
    matched = match_menus(voc_text, menus)
    processable = bool(matched)
    result = {"is_processable": processable, "matched_menus": matched,
              "menu_counts": {}, "is_frequent": False, "guidance_draft": None,
              "account_info": None, "business_data": []}
    if processable:
        for m in matched:
            conn.execute(
                "INSERT INTO menu_counts(menu, count) VALUES (?,1) "
                "ON CONFLICT(menu) DO UPDATE SET count = count + 1", (m,))
            result["menu_counts"][m] = conn.execute(
                "SELECT count FROM menu_counts WHERE menu=?", (m,)).fetchone()[0]
        frequent = [m for m, c in result["menu_counts"].items() if c >= FREQUENT_THRESHOLD]
        result["is_frequent"] = bool(frequent)
        if frequent:
            u = conn.execute("SELECT * FROM users WHERE user_id=?", (registrant_id,)).fetchone()
            result["account_info"] = dict(u) if u else None
            qs = ",".join("?" * len(frequent))
            rows = conn.execute(
                f"SELECT * FROM business_data WHERE user_id=? AND menu IN ({qs})",
                (registrant_id, *frequent)).fetchall()
            result["business_data"] = [dict(r) for r in rows]
    else:
        result["guidance_draft"] = generate_guidance(voc_text, use_api=use_api)
    conn.execute(
        "INSERT INTO voc_history(registrant_id, voc_text, is_processable, matched_menus, guidance_draft)"
        " VALUES (?,?,?,?,?)",
        (registrant_id, voc_text, int(processable), "|".join(matched), result["guidance_draft"]))
    conn.commit()
    return result
