"""VOC 판정·저장·누적(이력에서 계산)·모의 DB 조회."""
from .db import load_menus, normalize, validate_menus
from datetime import datetime, timezone

from .guidance import generate_guidance_with_source

FREQUENT_THRESHOLD = 3
SIMILARITY_THRESHOLD = 0.5


def match_menus(voc_text, menus):
    """정규화한 본문에서 긴 후보부터 겹치지 않게 매칭. 본문 등장 순서로 메뉴 반환."""
    validate_menus(menus)
    text = normalize(voc_text)
    terms = sorted(
        ((normalize(t), m["name"]) for m in menus for t in [m["name"], *m.get("aliases", [])]),
        key=lambda x: -len(x[0]))
    covered = [False] * len(text)
    first_pos = {}
    for term, menu in terms:
        if not term:
            continue
        start = text.find(term)
        while start != -1:
            end = start + len(term)
            if not any(covered[start:end]):
                covered[start:end] = [True] * len(term)
                first_pos[menu] = min(first_pos.get(menu, start), start)
                start = text.find(term, end)
            else:
                start = text.find(term, start + 1)
    return sorted(first_pos, key=first_pos.get)


def _bigrams(text):
    t = normalize(text)
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} - {""}


def similarity(a, b):
    """공백 제거 후 글자 2개 묶음(bigram) 집합의 자카드 유사도(0~1)."""
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def find_similar_voc(conn, voc_text, threshold=SIMILARITY_THRESHOLD):
    """메뉴명으로 처리 가능 판정된 과거 VOC 중 가장 유사한 건(유사도 >= 기준).

    유사 판정으로 처리된 건은 기준에서 제외해 유사의 유사로 번지는 것을 막는다.
    동점이면 최근 건을 고른다. 없으면 None.
    """
    best, best_score = None, threshold
    for r in conn.execute(
            "SELECT id, voc_text, matched_menus FROM voc_history WHERE is_processable=1"
            " AND COALESCE(match_source, 'menu')='menu' ORDER BY id DESC"):
        score = similarity(voc_text, r["voc_text"])
        if score > best_score or (best is None and score == best_score):
            best_score = score
            best = {"id": r["id"], "voc_text": r["voc_text"],
                    "menus": [m for m in r["matched_menus"].split("|") if m],
                    "similarity": round(score, 2)}
    return best


def get_menu_counts(conn):
    """메뉴별 누적: voc_menu_matches(이력)에서 계산."""
    return {r["menu"]: r["count"] for r in conn.execute(
        "SELECT menu, COUNT(*) AS count FROM voc_menu_matches GROUP BY menu")}


def validate_input(voc_text, registrant_id):
    warnings = []
    if not (voc_text or "").strip():
        warnings.append("VOC 본문을 입력하세요.")
    if not (registrant_id or "").strip():
        warnings.append("등록자 ID를 입력하세요.")
    return {"is_valid": not warnings, "warnings": warnings}


def lookup_mock_db(conn, registrant_id, frequent_menus):
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (registrant_id,)).fetchone()
    if u:
        account = {"found": True, "account": dict(u)}
    else:
        account = {"found": False, "account": None}
    qs = ",".join("?" * len(frequent_menus))
    rows = conn.execute(
        f"SELECT * FROM business_data WHERE user_id=? AND menu IN ({qs}) ORDER BY id",
        (registrant_id, *frequent_menus)).fetchall()
    return account, [dict(r) for r in rows]


def process_voc(conn, voc_text, registrant_id, menus=None, use_api=True):
    v = validate_input(voc_text, registrant_id)
    if not v["is_valid"]:
        return {"error": " ".join(v["warnings"]), "warnings": v["warnings"],
                "input_validation": v}
    voc_text = voc_text.strip()
    registrant_id = registrant_id.strip()
    menus = menus or load_menus()
    matched = match_menus(voc_text, menus)
    similar = None
    if matched:
        match_source = "menu"
    else:
        similar = find_similar_voc(conn, voc_text)
        if similar:
            matched = similar["menus"]
        match_source = "similar" if similar else None
    processable = bool(matched)
    guidance, source = (None, None) if processable else generate_guidance_with_source(
        voc_text, use_api=use_api)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        "INSERT INTO voc_history(registrant_id, voc_text, is_processable, matched_menus,"
        " guidance_draft, guidance_source, created_at, match_source, similar_voc_id,"
        " similarity) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (registrant_id, voc_text, int(processable), "|".join(matched), guidance, source,
         created_at, match_source, similar and similar["id"],
         similar and similar["similarity"]))
    conn.executemany("INSERT INTO voc_menu_matches(voc_id, menu) VALUES (?,?)",
                     [(cur.lastrowid, m) for m in matched])
    conn.commit()
    counts = get_menu_counts(conn)
    snapshot = {m: counts[m] for m in matched}
    frequent = [m for m in matched if snapshot[m] >= FREQUENT_THRESHOLD]
    account, business = (None, [])
    if frequent:
        account, business = lookup_mock_db(conn, registrant_id, frequent)
    return {"is_processable": processable, "matched_menus": matched,
            "menu_counts": snapshot, "count_snapshot": snapshot,
            "frequent_menus": frequent, "is_frequent": bool(frequent),
            "guidance_draft": guidance, "guidance_source": source,
            "created_at": created_at, "account_info": account,
            "business_data": business, "input_validation": v, "voc_id": cur.lastrowid,
            "match_source": match_source, "similar_voc": similar}
