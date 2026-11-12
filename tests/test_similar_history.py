"""처리 가능 VOC의 유사 과거 VOC 처리 이력(모의 처리 내용 포함)."""
import pytest

from voc import agent
from voc.db import MOCK_HANDLING, backfill_mock_handling, connect, init_db
from voc.service import bigram_scorer, find_similar_history, process_voc, save_voc

MENUS = [{"name": "비밀유지계약", "aliases": ["서약서"]},
         {"name": "사용자 관리", "aliases": ["사용자 권한"]}]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "h.db")
    init_db(c, reset=True, menus=MENUS)
    yield c
    c.close()


def add(conn, text, menus, rid="u001", created="2026-11-10T01:00:00Z"):
    vid, _ = save_voc(conn, rid, text, menus, None, None, "menu" if menus else None)
    conn.execute("UPDATE voc_history SET created_at=? WHERE id=?", (created, vid))
    conn.commit()
    return vid


def note(conn, vid):
    return conn.execute("SELECT handling_note, handled_at FROM voc_history WHERE id=?",
                        (vid,)).fetchone()


def test_backfill_mock_handling(conn):
    a = add(conn, "서약서 제출 현황 알려주세요", ["비밀유지계약"])
    b = add(conn, "점심 메뉴", [])
    c = add(conn, "사용자 권한 요청", ["사용자 관리"])
    conn.execute("UPDATE voc_history SET handling_note='실제 처리' WHERE id=?", (c,))
    conn.commit()
    assert backfill_mock_handling(conn) == 1
    n, at = note(conn, a)
    assert n == "(모의) " + MOCK_HANDLING["비밀유지계약"] and at == "2026-11-11"
    assert note(conn, b)[0] is None  # 처리 불가 건은 처리 내용 없음
    assert note(conn, c)[0] == "실제 처리"  # 이미 있는 처리 내용은 유지
    assert backfill_mock_handling(conn) == 0  # 다시 실행해도 그대로


def test_find_similar_history_same_menu_ranked(conn):
    a = add(conn, "서약서 제출 현황 알려주세요", ["비밀유지계약"], rid="가나다")
    b = add(conn, "서약서 양식이 바뀌었나요", ["비밀유지계약"], rid="u002")
    add(conn, "사용자 권한 요청 서약서 현황", ["사용자 관리"])  # 다른 메뉴
    cur = add(conn, "서약서 제출 현황 다시 알려주세요", ["비밀유지계약"], rid="가나다",
              created="2026-11-20T01:00:00Z")
    backfill_mock_handling(conn)
    hist = find_similar_history(conn, "서약서 제출 현황 다시 알려주세요", ["비밀유지계약"],
                                exclude_id=cur, registrant_id="가나다")
    assert [h["id"] for h in hist][0] == a  # 가장 비슷한 건이 먼저
    assert b not in [h["id"] for h in hist] or hist[-1]["id"] == b
    top = hist[0]
    assert top["same_registrant"] and top["created_at"].startswith("2026-11-10")
    assert top["handling_note"].startswith("(모의)") and top["menus"] == ["비밀유지계약"]
    assert cur not in [h["id"] for h in hist]


def test_find_similar_history_threshold_and_empty(conn):
    add(conn, "서약서 양식", ["비밀유지계약"])
    assert find_similar_history(conn, "완전히 다른 내용의 문의입니다", ["비밀유지계약"]) == []
    assert find_similar_history(conn, "서약서 양식", []) == []


def test_scorer_failure_falls_back_to_bigram(conn):
    a = add(conn, "서약서 제출 현황 알려주세요", ["비밀유지계약"])

    def broken(query, texts):
        raise RuntimeError("throttled")
    hist = find_similar_history(conn, "서약서 제출 현황 알려주세요", ["비밀유지계약"],
                                scorer=broken)
    assert [h["id"] for h in hist] == [a]
    assert bigram_scorer("서약서", ["서약서", "점심"]) == [1.0, 0.0]


def test_graph_adds_history_for_processable(conn):
    first = process_voc(conn, "서약서 제출 현황 알려주세요", "가나다", menus=MENUS)
    assert first["similar_history"] == [] and "history" in first["steps"]
    backfill_mock_handling(conn)
    again = process_voc(conn, "서약서 제출 현황 다시 알려주세요", "가나다", menus=MENUS)
    h = again["similar_history"]
    assert h[0]["id"] == first["voc_id"] and h[0]["same_registrant"]
    assert h[0]["handling_note"].startswith("(모의)")
    assert again["steps"].index("history") == again["steps"].index("record") + 1


def test_unprocessable_has_no_history(conn):
    r = process_voc(conn, "점심 메뉴 추천", "u001", menus=MENUS)
    assert r["similar_history"] == [] and "history" not in r["steps"]


def test_lookup_agent_gets_history(conn, monkeypatch):
    monkeypatch.setenv("VOC_USE_LLM", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy")
    monkeypatch.setattr("voc.graph.history_scorer", lambda llm_on: bigram_scorer)
    seen = {}

    def lookup(rid, menus, history=None):
        seen["history"] = history
        return {"summary": "s", "tool_calls": []}
    monkeypatch.setattr(agent, "summarize_frequent", lookup)
    for t in ("서약서 제출 현황 알려주세요", "서약서 제출 현황 요청", "서약서 제출 현황 다시"):
        process_voc(conn, t, "가나다", menus=MENUS)
        backfill_mock_handling(conn)
    assert seen["history"] and seen["history"][0]["handling_note"].startswith("(모의)")


def test_lookup_message_includes_history():
    msg = agent._lookup_message("가나다", ["비밀유지계약"], [
        {"created_at": "2026-11-10T01:00:00Z", "registrant_id": "가나다", "same_registrant": True,
         "voc_text": "서약서 제출 현황", "handling_note": "(모의) 엑셀 회신", "similarity": 0.8}])
    assert "2026-11-10" in msg and "(모의) 엑셀 회신" in msg and "같은 등록자" in msg
    assert "유사 VOC 처리 이력" in agent.LOOKUP_PROMPT


def test_app_labels_history():
    import app
    assert "history" in app.STEP_LABELS
