"""VOC 판정 단계별 함수(규칙 매칭·글자 유사도·저장·누적·모의 DB 조회).

전체 흐름은 voc/graph.py의 LangGraph가 이 함수들을 노드로 엮어 실행한다.
"""
from datetime import datetime, timezone

from .db import normalize, validate_menus

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


def match_policy(voc_text, policies):
    """본문(공백 무시)에 정책 표현이 있으면 그 정책, 없으면 None. 1차 규칙보다 먼저 적용한다."""
    text = normalize(voc_text)
    for p in policies:
        if any(normalize(t) and normalize(t) in text for t in p.get("patterns", [])):
            return p
    return None


def _bigrams(text):
    t = normalize(text)
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} - {""}


def similarity(a, b):
    """공백 제거 후 글자 2개 묶음(bigram) 집합의 자카드 유사도(0~1)."""
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


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


def process_voc(conn, voc_text, registrant_id, menus=None, use_api=True):
    """VOC 1건 판정·저장. 흐름은 voc/graph.py(LangGraph) 참고."""
    from .graph import run_voc

    return run_voc(conn, voc_text, registrant_id, menus=menus, use_api=use_api)
