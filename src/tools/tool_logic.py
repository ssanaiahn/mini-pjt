"""[tools] 에이전트용 도구 로직(읽기 전용).

MCP 서버(src/tools/mcp_server.py)가 list_menus·get_menu_count·lookup_account·lookup_business_data를,
판정 에이전트의 로컬 도구(src/judgement/agent.py)가 search_similar_vocs를 노출한다.
모든 SQL은 파라미터 바인딩(?)으로 입력값을 쿼리 구조에 섞지 않는다.
"""
import json

from ..retrieval.lexical import bigram_candidates
from ..shared import db, llm
from ..shared.config import load_menus


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
                  for m in load_menus()])


def search_similar_vocs(voc_text, k=3):
    """하이브리드 검색(LLM 사용 가능 시 Titan+Chroma+글자 유사도) 또는 글자 유사도(대체)."""
    conn = _conn()
    try:
        if llm.llm_enabled():
            from ..retrieval.vectorstore import search
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
