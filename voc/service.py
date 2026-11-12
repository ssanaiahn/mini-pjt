"""VOC 판정 단계별 함수(규칙 매칭·글자 유사도·저장·누적·모의 DB 조회).

전체 흐름은 voc/graph.py의 LangGraph가 이 함수들을 노드로 엮어 실행한다.
"""
import re
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
    """정책에 해당하면 그 정책, 아니면 None. 1차 규칙보다 먼저 적용한다.

    patterns(공백 무시 부분 문자열) 또는 regex(원문 검색)가 맞고, require_any가 있으면
    그중 하나(접속·사용·승인 등)도 본문에 있어야 한다. 그래서 해외 법인 관련 보안 신고나
    개선 제안처럼 사용 요청이 아닌 문의는 막지 않는다.
    """
    text = normalize(voc_text)
    for p in policies:
        hit = (any(normalize(t) and normalize(t) in text for t in p.get("patterns", []))
               or any(re.search(rx, voc_text or "") for rx in p.get("regex", [])))
        need = p.get("require_any") or []
        if hit and (not need or any(normalize(t) in text for t in need)):
            return p
    return None


def needs_recheck(voc_text, menus, matched):
    """1차 규칙으로 매칭됐지만 재확인 키워드(recheck_terms)가 있어 에이전트가 다시 판단할 메뉴.

    예: '접속'(사용자 관리 별칭)이 있어도 'AD'·'비밀번호'가 있으면 통합인증 문의일 수 있다.
    영문 키워드는 단어 단위(대소문자 무시)로, 한글 키워드는 공백 무시 부분 문자열로 찾는다.
    """
    text = normalize(voc_text)
    out = []
    for m in menus:
        if m["name"] not in matched:
            continue
        for t in m.get("recheck_terms", []):
            if t.isascii():
                hit = re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", voc_text or "", re.I)
            else:
                hit = normalize(t) in text
            if hit:
                out.append(m["name"])
                break
    return out


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


HISTORY_K = 5
HISTORY_THRESHOLD = 0.2  # 글자 유사도 기준(의미 검색 scorer는 자체 threshold 속성 사용)


def bigram_scorer(query, texts):
    """글자 2개 묶음 자카드 유사도 목록."""
    return [similarity(query, t) for t in texts]


bigram_scorer.threshold = HISTORY_THRESHOLD


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
