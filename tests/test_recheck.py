"""재확인 키워드: 1차 규칙에 걸려도 키워드(AD·비밀번호 등)가 있으면 판정 에이전트가 다시 판단."""
import pytest

from voc import agent
from voc.db import connect, init_db, load_menus
from voc.service import bigram_scorer, needs_recheck, process_voc

MENUS = [{"name": "보안 신고", "aliases": []},
         {"name": "사용자 관리", "aliases": ["접속"],
          "recheck_terms": ["AD", "MFA", "OTP", "통합인증", "비밀번호"]}]
AD_VOC = "사내 시스템 접속할 때 ad 인증 비밀번호를 잊어버렸습니다. 비밀번호 재발급 해주세요."


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "r.db")
    init_db(c, reset=True, menus=MENUS)
    yield c
    c.close()


@pytest.fixture
def llm_on(monkeypatch):
    monkeypatch.setenv("VOC_USE_LLM", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy")
    monkeypatch.setattr("voc.graph.generate_guidance_with_source",
                        lambda *a, **k: ("안내", "claude"))
    monkeypatch.setattr("voc.graph.history_scorer", lambda llm_on: bigram_scorer)
    monkeypatch.setattr(agent, "summarize_frequent", lambda *a, **k: {"summary": "s", "tool_calls": []})
    calls = []

    def set_judge(result):
        monkeypatch.setattr(agent, "judge_voc", lambda t: calls.append(t) or result)
    return calls, set_judge


def test_config_has_recheck_terms():
    um = {m["name"]: m for m in load_menus()}["사용자 관리"]
    assert {"AD", "MFA", "OTP", "통합인증", "비밀번호"} <= set(um["recheck_terms"])


@pytest.mark.parametrize("text, matched, expected", [
    (AD_VOC, ["사용자 관리"], ["사용자 관리"]),
    ("MFA 등록이 안 돼서 접속 못 해요", ["사용자 관리"], ["사용자 관리"]),
    ("포털 접속이 안 돼요", ["사용자 관리"], []),
    ("다운로드 download 하려는데 접속이 끊겨요", ["사용자 관리"], []),  # 영문 단어 속 ad는 제외
    (AD_VOC, ["보안 신고"], []),  # 재확인 키워드가 없는 메뉴
])
def test_needs_recheck(text, matched, expected):
    assert needs_recheck(text, MENUS, matched) == expected


def test_recheck_sends_to_agent_and_rejects(conn, llm_on):
    calls, set_judge = llm_on
    set_judge({"processable": False, "menus": [], "reason": "AD 통합인증은 받지 않는 요청",
               "similar_voc_ids": [], "tool_calls": ["list_menus"]})
    r = process_voc(conn, AD_VOC, "u001", menus=MENUS)
    assert len(calls) == 1 and not r["is_processable"]
    assert r["guidance_draft"] == "안내"
    assert r["steps"][:6] == ["validate", "guard", "policy_check", "rule_match", "agent_judge",
                              "guidance"]
    assert conn.execute("SELECT COUNT(*) FROM voc_menu_matches").fetchone()[0] == 0


def test_recheck_agent_can_accept(conn, llm_on):
    calls, set_judge = llm_on
    set_judge({"processable": True, "menus": ["사용자 관리"], "reason": "포털 계정 문의",
               "similar_voc_ids": [], "tool_calls": []})
    r = process_voc(conn, AD_VOC, "u001", menus=MENUS)
    assert r["is_processable"] and r["matched_menus"] == ["사용자 관리"]
    assert r["match_source"] == "agent"


def test_recheck_agent_error_keeps_rule_result(conn, llm_on):
    calls, set_judge = llm_on
    set_judge({"error": "ThrottlingException: limit"})
    r = process_voc(conn, AD_VOC, "u001", menus=MENUS)
    assert r["is_processable"] and r["matched_menus"] == ["사용자 관리"]
    assert r["match_source"] == "menu" and r["agent_error"].startswith("Throttling")


def test_no_recheck_without_keyword(conn, llm_on):
    calls, _ = llm_on
    r = process_voc(conn, "포털 접속이 안 돼요", "u001", menus=MENUS)
    assert calls == [] and r["is_processable"] and r["match_source"] == "menu"


def test_rule_mode_keeps_rule_result(conn):
    r = process_voc(conn, AD_VOC, "u001", menus=MENUS)  # conftest: LLM 미사용
    assert r["is_processable"] and r["matched_menus"] == ["사용자 관리"]
