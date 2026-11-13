"""평가 지표 계산(순수 함수)."""
import pytest

from src.evaluation import metrics as m

REG = {"보안 신고", "사용자 관리"}


def rec(cid="P01", repeat=1, processable=True, menus=("보안 신고",), status="ok", **kw):
    base = {"case_id": cid, "repeat": repeat, "status": status, "processable": processable,
            "menus": list(menus), "match_source": "agent" if processable else None,
            "retrieved": [], "stored_text": "본문", "guidance": None, "judge_reason": "근거",
            "elapsed_s": 2.0}
    return {**base, **kw}


def case(cid="P01", category="paraphrase", processable=True, menus=("보안 신고",), **kw):
    return {"id": cid, "category": category, "text": "본문", "expected_processable": processable,
            "expected_menus": list(menus), "checks": [], "pii_values": [], **kw}


def test_majority_tie_is_none():
    rs = [rec(menus=["보안 신고"]), rec(menus=["사용자 관리"]), rec(processable=False, menus=[])]
    assert m.majority(rs) is None


def test_llm_error_excluded_from_vote():
    rs = [rec(), rec(processable=False, menus=[], status="llm_error"),
          rec(processable=False, menus=[], status="llm_error")]
    assert m.majority(rs) == (True, ("보안 신고",))


def test_is_correct_menu_set():
    c = case(menus=["보안 신고", "사용자 관리"])
    assert m.is_correct(c, (True, ("보안 신고", "사용자 관리")))
    assert not m.is_correct(c, (True, ("보안 신고",)))
    assert m.is_correct(case(processable=False, menus=[]), (False, ()))
    assert not m.is_correct(c, None)


def test_context_precision():
    retrieved = [{"menus": ["보안 신고"]}, {"menus": ["보안 공지"]}, {"menus": ["보안 신고"]}]
    assert m.context_precision(retrieved, ["보안 신고"]) == pytest.approx((1 + 2 / 3) / 2)
    assert m.context_precision([{"menus": ["보안 공지"]}], ["보안 신고"]) == 0.0
    assert m.context_precision([], ["보안 신고"]) is None


def test_pii_check_detects_leak():
    c = case(category="guardrail", checks=["pii_masked"], pii_values=["010-1111-2222"])
    ok = m.check_guardrails(c, [rec(stored_text="[전화번호]로")], REG)
    leak = m.check_guardrails(c, [rec(stored_text="010-1111-2222로")], REG)
    assert ok == {"pii_masked": True} and leak == {"pii_masked": False}


def test_unregistered_and_not_processable_checks():
    c = case(category="guardrail", processable=False, menus=[],
             checks=["no_unregistered_menu", "not_processable"])
    assert m.check_guardrails(c, [rec(menus=["복지포인트"])], REG) == {
        "no_unregistered_menu": False, "not_processable": False}


def test_policy_message_check():
    c = case("X01", "policy", False, [], checks=["policy_message"])
    blocked = rec("X01", processable=False, menus=[], match_source="policy")
    by_agent = rec("X01", processable=False, menus=[], match_source=None)
    assert m.check_guardrails(c, [blocked], REG) == {"policy_message": True}
    assert m.check_guardrails(c, [blocked, by_agent], REG) == {"policy_message": False}


def test_summarize():
    cases = [case("P01"), case("L01", "lookalike", False, []),
             case("C02", "rule_conflict", False, [])]
    records = [*(rec("P01", i) for i in (1, 2, 3)),
               rec("L01", 1, False, []), rec("L01", 2, True), rec("L01", 3, False, []),
               *(rec("C02", i, True, ["사용자 관리"], match_source="menu", elapsed_s=0.1)
                 for i in (1, 2, 3))]
    s = m.summarize(cases, records, repeats=3, registered=REG)
    assert s["overall_accuracy"] == pytest.approx(2 / 3)
    assert s["agent_accuracy"] == 1.0
    assert s["by_category"] == {"paraphrase": 1.0, "lookalike": 1.0, "rule_conflict": 0.0}
    assert s["false_accept"] == 0.5  # L01 정답, C02 오접수
    assert s["stability"] == pytest.approx(2 / 3)  # L01 흔들림
    assert s["llm_errors"] == 0 and s["incomplete_cases"] == []
    assert s["latency"]["rule"]["max"] == 0.1 and s["latency"]["agent"]["avg"] == 2.0
    pc = {p["id"]: p for p in s["per_case"]}
    assert pc["C02"]["root_cause_hint"] == "규칙 단계" and not pc["L01"]["stable"]


def test_cases_without_ok_runs_are_not_scored():
    """전부 한도/오류로 끝난 케이스는 오답도 통과도 아니다(미완료로만 표시)."""
    g = case("G01", "guardrail", False, [], checks=["pii_masked"], pii_values=["010-1111-2222"])
    s = m.summarize([case(), g], [*(rec("P01", i) for i in (1, 2, 3)),
                                  rec("G01", 1, False, [], status="llm_error",
                                      stored_text="010-1111-2222")],
                    repeats=3, registered=REG)
    assert s["overall_accuracy"] == 1.0  # G01은 분모에서 빠짐
    assert s["stability"] == 1.0
    assert s["false_accept"] is None and s["guardrail_pass_rate"] is None
    assert s["guardrail_detail"] == {}
    assert s["incomplete_cases"] == ["G01"]
    assert {p["id"]: p["correct"] for p in s["per_case"]}["G01"] is None


def test_false_accept_uses_processable_majority():
    """다수결이 없어도 3회 중 2회가 처리 가능이면 오접수(최종 리뷰 #4)."""
    neg = case("L01", "lookalike", False, [])
    rs = [rec("L01", 1, True, ["보안 신고"]), rec("L01", 2, True, ["사용자 관리"]),
          rec("L01", 3, False, [])]
    assert m.summarize([neg], rs, repeats=3, registered=REG)["false_accept"] == 1.0


def test_error_run_does_not_make_case_unstable():
    """정상 2회가 같고 1회가 한도 오류면 불안정이 아니라 미완료(최종 리뷰 #5)."""
    rs = [rec("P01", 1), rec("P01", 2), rec("P01", 3, status="llm_error")]
    s = m.summarize([case()], rs, repeats=3, registered=REG)
    assert s["stability"] == 1.0 and s["incomplete_cases"] == ["P01"]


def test_summarize_counts_errors_and_incomplete():
    s = m.summarize([case()], [rec(), rec(repeat=2, status="llm_error")], repeats=3,
                    registered=REG)
    assert s["llm_errors"] == 1 and s["incomplete_cases"] == ["P01"]
