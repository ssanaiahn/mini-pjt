"""에이전트용 도구 로직(읽기 전용).

MCP 서버(voc/mcp_server.py)가 list_menus·get_menu_count·lookup_account·lookup_business_data를,
앱 프로세스의 로컬 도구(voc/agent.py)가 search_similar_vocs를 노출한다.
"""
import json

from . import llm
from . import db


def _json(v):
    return json.dumps(v, ensure_ascii=False)


def _conn():
    c = db.connect()
    db.init_db(c)
    return c


def list_menus():
    """등록 메뉴명·별칭과 업무 범위(scope: 설명, 받는 요청, 받지 않는 요청)."""
    return _json([{"name": m["name"], "aliases": m.get("aliases", []),
                   **({"scope": m["scope"]} if m.get("scope") else {})}
                  for m in db.load_menus()])


def search_similar_vocs(voc_text, k=3):
    """의미 검색(LLM 사용 가능 시 Titan+Chroma) 또는 글자 유사도(대체)."""
    from .service import bigram_candidates

    conn = _conn()
    try:
        if llm.llm_enabled():
            from .vectorstore import search
            return _json({"method": "embedding", "results": search(conn, voc_text, k=k)})
        return _json({"method": "bigram", "results": bigram_candidates(conn, voc_text, k=k)})
    finally:
        conn.close()


def get_menu_count(menu):
    conn = _conn()
    try:
        row = conn.execute("SELECT COUNT(*) FROM voc_menu_matches WHERE menu=?", (menu,)).fetchone()
        return _json({"menu": menu, "count": row[0]})
    finally:
        conn.close()


def lookup_account(user_id):
    conn = _conn()
    try:
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return _json({"found": bool(u), "account": dict(u) if u else None})
    finally:
        conn.close()


def lookup_business_data(user_id, menu):
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM business_data WHERE user_id=? AND menu=? ORDER BY id",
                            (user_id, menu)).fetchall()
        return _json([dict(r) for r in rows])
    finally:
        conn.close()
