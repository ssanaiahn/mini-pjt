"""서비스 정책: 해외 법인 임직원·해외 법인 접속은 1차 규칙보다 먼저 막고 고정 문구로 종료."""
import pytest

from src.judgement import agent as judge_agent
from src.lookup import agent as lookup_agent
from src.shared.db import connect, init_db
from src.shared.config import load_policies
from src.guardrails.policy import match_policy
from src.workflows.voc_graph import process_voc

MENUS = [{"name": "보안 신고", "aliases": []},
         {"name": "사용자 관리", "aliases": ["사용자 승인", "접속"]}]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "p.db")
    init_db(c, reset=True, menus=MENUS)
    yield c
    c.close()


@pytest.fixture
def policies():
    return load_policies()


def test_load_policies_from_config(policies):
    p = {x["id"]: x for x in policies}["overseas_block"]
    assert "국내 임직원 전용" in p["message"] and "해외 법인" in p["patterns"]


@pytest.mark.parametrize("text, blocked", [
    ("해외법인 직원인데 포털 사용 승인 부탁드립니다", True),
    ("베트남 현지 법인 소속인데 사용 승인 부탁드립니다", True),
    ("미국 법인 직원인데 포털 접속 권한 요청드립니다", True),
    ("중국법인 소속 직원 사용자 승인 부탁", True),
    ("해외 지사 직원 접속 요청", True),
    # 접속·사용·승인·권한·계정 요청이 아니면 막지 않는다(보안 신고·개선 제안은 받아야 함)
    ("해외 법인 서버에서 고객 개인정보 유출 정황이 있어 보안 신고합니다", False),
    ("해외 임직원 대상 보안 교육 방식 개선 제안드립니다", False),
    ("베트남 현지 법인 소속입니다", False),
    ("법인카드 사용 승인 문의", False),
    ("해외 임직원 계정을 열어 주세요", True),
    ("해외 법인에서 접속이 안 돼요", True),
    ("해외 출장 중인데 호텔에서 포털 접속이 안 됩니다", False),
    ("보안 신고 문의", False),
])
def test_match_policy(policies, text, blocked):
    assert (match_policy(text, policies) is not None) == blocked


def test_policy_blocks_before_rule_and_agent(conn, monkeypatch, policies):
    monkeypatch.setenv("VOC_USE_LLM", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy")
    monkeypatch.setattr(judge_agent, "judge_voc", lambda t: pytest.fail("agent called"))
    monkeypatch.setattr("src.workflows.voc_graph.generate_guidance_with_source",
                        lambda *a, **k: pytest.fail("LLM guidance called"))
    r = process_voc(conn, "해외 법인 직원도 포털에 접속할 수 있게 열어 주세요", "u001", menus=MENUS)
    msg = {x["id"]: x for x in policies}["overseas_block"]["message"]
    assert not r["is_processable"] and r["matched_menus"] == []
    assert r["match_source"] == "policy" and r["guidance_source"] == "policy"
    assert r["guidance_draft"] == msg
    assert r["steps"] == ["validate", "guard", "policy_check", "record"]
    row = conn.execute("SELECT match_source, judge_reason, is_processable FROM voc_history").fetchone()
    assert tuple(row) == ("policy", "정책: overseas_block", 0)
    assert conn.execute("SELECT COUNT(*) FROM voc_menu_matches").fetchone()[0] == 0


def test_business_trip_not_blocked(conn):
    r = process_voc(conn, "해외 출장 중인데 호텔에서 포털 접속이 안 됩니다", "u001", menus=MENUS)
    assert r["is_processable"] and r["matched_menus"] == ["사용자 관리"]
    assert r["steps"][:4] == ["validate", "guard", "policy_check", "rule_match"]


def test_app_labels_cover_policy():
    from src.ui import app
    assert "policy" in app.SOURCE_LABELS and "policy_check" in app.STEP_LABELS
