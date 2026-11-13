"""LangGraph 흐름 + 에이전트 경로(에이전트·조회 요약은 가짜로 대체, 네트워크 없음)."""
import pytest

from src.judgement import agent as judge_agent
from src.lookup import agent as lookup_agent
from src.shared.db import connect, init_db
from src.workflows.voc_graph import build_graph
from src.guardrails.pii import mask_pii
from src.retrieval.lexical import bigram_scorer
from src.workflows.voc_graph import process_voc

MENUS = [
    {"name": "보안 신고", "aliases": []},
    {"name": "사용자 관리", "aliases": ["사용자 권한"]},
]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "g.db")
    init_db(c, reset=True, menus=MENUS)
    yield c
    c.close()


@pytest.fixture
def llm_on(monkeypatch):
    monkeypatch.setenv("VOC_USE_LLM", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy")
    calls = {"judge": [], "lookup": [], "guidance": []}

    def guidance(text, use_api=True, reason=None, hints=None):
        calls["guidance"].append(reason)
        return "에이전트 안내", "claude"
    monkeypatch.setattr("src.workflows.voc_graph.generate_guidance_with_source", guidance)
    monkeypatch.setattr(lookup_agent, "summarize_frequent", lambda rid, menus, history=None: calls["lookup"].append(
        (rid, menus)) or {"summary": "요약", "tool_calls": ["lookup_account"]})
    # 유사 VOC 이력의 임베딩(Titan) 호출 대신 글자 유사도(네트워크 없음)
    monkeypatch.setattr("src.workflows.voc_graph.history_scorer", lambda llm_on: bigram_scorer)
    return calls


def set_judge(monkeypatch, calls, result):
    def judge(text):
        calls["judge"].append(text)
        return result
    monkeypatch.setattr(judge_agent, "judge_voc", judge)


def run(conn, text, rid="u001"):
    return process_voc(conn, text, rid, menus=MENUS)


def test_menu_match_skips_agent(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"error": "should not be called"})
    r = run(conn, "사용자 권한 신청이 안 돼요")
    assert r["match_source"] == "menu" and llm_on["judge"] == []
    assert r["steps"] == ["validate", "guard", "policy_check", "rule_match", "record", "history"]


def test_agent_judges_processable(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"processable": True, "menus": ["사용자 관리", "없는메뉴"],
                                    "reason": "계정 잠금은 사용자 관리 업무", "similar_voc_ids": [],
                                    "tool_calls": ["list_menus", "search_similar_vocs"]})
    r = run(conn, "계정이 잠겨서 로그인이 안 돼요")
    assert r["is_processable"] and r["match_source"] == "agent"
    assert r["matched_menus"] == ["사용자 관리"]  # 등록되지 않은 메뉴는 버림
    assert r["judge"]["tool_calls"] == ["list_menus", "search_similar_vocs"]
    assert r["count_snapshot"] == {"사용자 관리": 1}
    assert r["steps"] == ["validate", "guard", "policy_check", "rule_match", "agent_judge", "record", "history"]
    row = conn.execute("SELECT match_source, judge_reason FROM voc_history").fetchone()
    assert tuple(row) == ("agent", "계정 잠금은 사용자 관리 업무")


def test_agent_judges_unprocessable_then_guidance(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"processable": False, "menus": [], "reason": "식당 문의",
                                    "similar_voc_ids": [], "tool_calls": ["list_menus"]})
    r = run(conn, "오늘 점심 메뉴 추천해 주세요")
    assert not r["is_processable"] and r["guidance_draft"] == "에이전트 안내"
    assert llm_on["guidance"] == ["식당 문의"]  # 판정 근거를 문구 생성에 전달
    assert r["steps"][-2:] == ["guidance", "record"]


def test_agent_processable_without_valid_menu_is_unprocessable(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"processable": True, "menus": ["없는메뉴"], "reason": "?",
                                    "similar_voc_ids": [], "tool_calls": []})
    assert run(conn, "알 수 없는 요청")["is_processable"] is False


def test_agent_error_falls_back_to_bigram(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"error": "ThrottlingException: too many tokens"})
    run(conn, "보안 신고 메일 주소가 어디인가요")
    r = run(conn, "보안 신고 메일 주소가 어딘가요")  # 메뉴명 있음 → 규칙
    assert r["match_source"] == "menu"
    r = run(conn, "보안신거 메일 주소가 어디인가요")  # 오타: 에이전트 실패 → 글자 유사도
    assert r["agent_error"].startswith("ThrottlingException")
    assert r["match_source"] == "similar" and r["matched_menus"] == ["보안 신고"]
    assert "similar_fallback" in r["steps"]


def test_frequent_calls_lookup_agent(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"error": "unused"})
    for _ in range(3):
        r = run(conn, "보안 신고 문의", "u002")
    assert r["is_frequent"] and r["lookup_summary"]["summary"] == "요약"
    assert llm_on["lookup"] == [("u002", ["보안 신고"])]
    assert r["account_info"]["found"] is True  # 규칙 조회 결과도 함께 표시


def test_rule_mode_never_calls_agents(conn, monkeypatch):
    monkeypatch.setattr(judge_agent, "judge_voc", lambda t: pytest.fail("agent called"))
    monkeypatch.setattr(lookup_agent, "summarize_frequent", lambda *a: pytest.fail("agent called"))
    for _ in range(3):
        r = run(conn, "보안 신고 문의")
    assert r["mode"] == "rule" and r["lookup_summary"] is None
    assert run(conn, "점심 메뉴")["guidance_source"] == "template_no_key"


def test_pii_masked_before_save_and_agent(conn, monkeypatch, llm_on):
    set_judge(monkeypatch, llm_on, {"processable": False, "menus": [], "reason": "-",
                                    "similar_voc_ids": [], "tool_calls": []})
    r = run(conn, "연락처 010-1234-5678, 메일 kim@example.com 으로 회신 부탁")
    assert "010-1234-5678" not in llm_on["judge"][0] and "[전화번호]" in llm_on["judge"][0]
    assert set(r["pii_found"]) == {"전화번호", "이메일"}
    saved = conn.execute("SELECT voc_text FROM voc_history").fetchone()[0]
    assert "kim@example.com" not in saved and "[이메일]" in saved


def test_graph_input_is_masked(conn, monkeypatch, llm_on):
    """LangSmith는 그래프 입력을 기록하므로, 입력 상태부터 가린 본문이어야 한다."""
    import src.workflows.voc_graph as graph
    set_judge(monkeypatch, llm_on, {"processable": False, "menus": [], "reason": "-",
                                    "similar_voc_ids": [], "tool_calls": []})
    captured = []
    real_build = graph.build_graph

    def build(*a, **kw):
        g = real_build(*a, **kw)

        class Wrapped:
            def invoke(self, state, *ia, **ikw):
                captured.append(dict(state))
                return g.invoke(state, *ia, **ikw)
        return Wrapped()
    monkeypatch.setattr(graph, "build_graph", build)
    r = run(conn, "연락처 010-1234-5678 회신 부탁")
    assert "010-1234-5678" not in captured[0]["voc_text"]
    assert "[전화번호]" in captured[0]["voc_text"]
    assert r["pii_found"] == ["전화번호"]


@pytest.mark.parametrize("text, masked", [
    ("010-2345-6789로 연락 주세요", "[전화번호]로 연락 주세요"),
    ("회신은 kim.minsu@example.com으로 부탁", "회신은 [이메일]으로 부탁"),
    ("주민 900101-1234567이고요", "주민 [주민번호]이고요"),
    ("번호 0101234567890123은 계좌", "번호 0101234567890123은 계좌"),  # 더 긴 숫자열 일부는 안 가림
    ("김철수@corp.com 으로 회신", "[이메일] 으로 회신"),  # 한글 아이디(최종 리뷰: R2 회귀)
    ("문의는 홍길동@회사.kr로", "문의는 [이메일]로"),
])
def test_mask_pii_with_korean_particles(text, masked):
    assert mask_pii(text)[0] == masked


def test_graph_passes_department_hints_to_guidance(conn, monkeypatch, llm_on):
    seen = {}

    def guidance(text, use_api=True, reason=None, hints=None):
        seen["hints"] = hints
        return "안내", "claude"
    monkeypatch.setattr("src.workflows.voc_graph.generate_guidance_with_source", guidance)
    set_judge(monkeypatch, llm_on, {"processable": False, "menus": [], "reason": "-",
                                    "similar_voc_ids": [], "tool_calls": []})
    menus = [{"name": "보안 신고", "aliases": [],
              "scope": {"excludes": ["출입카드 분실 (총무팀)", "부서 없음"]}}]
    process_voc(conn, "출입증 분실", "u001", menus=menus)
    assert seen["hints"] == ["출입카드 분실 (총무팀)"]


def test_mask_pii_patterns():
    text, found = mask_pii("주민 900101-1234567 / 01098765432 / a.b@c.co.kr")
    assert text == "주민 [주민번호] / [전화번호] / [이메일]"
    assert found == ["주민등록번호", "전화번호", "이메일"]
    assert mask_pii("보안 공지 문의") == ("보안 공지 문의", [])


def test_graph_structure(conn):
    g = build_graph(conn, MENUS, llm_on=True).get_graph()
    nodes = set(g.nodes) - {"__start__", "__end__"}
    assert nodes == {"validate", "guard", "policy_check", "rule_match", "agent_judge", "similar_fallback",
                     "guidance", "record", "history", "lookup"}
