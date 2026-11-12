"""라운드 리포트 렌더링과 CLI 진입 조건(네트워크 없음)."""
from evaluation import report, run_eval

INFO = {"date": "2026-11-12", "model": "m", "cases": 2, "repeats": 3,
        "langsmith_project": "voc-eval-round1", "commit": "abc1234", "ragas_method": "claude"}


def summary(**kw):
    base = {"overall_accuracy": 0.5, "agent_accuracy": 1.0, "by_category": {"paraphrase": 1.0},
            "false_accept": 0.0, "stability": 1.0, "context_precision_avg": 0.8,
            "guardrail_pass_rate": 0.5,
            "guardrail_detail": {"G01": {"pii_masked": False}},
            "latency": {"rule": {"avg": 0.1, "max": 0.2}, "agent": {"avg": 9.0, "max": 12.0}},
            "llm_errors": 0, "incomplete_cases": [],
            "per_case": [
                {"id": "P01", "category": "paraphrase", "text": "본문", "expected": (True, ("보안 신고",)),
                 "runs": [(True, ("보안 신고",))] * 3, "majority": (True, ("보안 신고",)),
                 "correct": True, "stable": True, "judge_reason": "근거", "match_source": "agent",
                 "root_cause_hint": None},
                {"id": "C02", "category": "rule_conflict", "text": "해외 접속", "expected": (False, ()),
                 "runs": [(True, ("사용자 관리",))] * 3, "majority": (True, ("사용자 관리",)),
                 "correct": False, "stable": True, "judge_reason": None, "match_source": "menu",
                 "root_cause_hint": "규칙 단계"}]}
    return {**base, **kw}


JUDGES = {"guidance": {"L01": {"scores": {"정중함": 5}, "overall": 3.2, "comment": "문의처 없음",
                               "guidance": "안내"}},
          "faithfulness": {}, "guidance_avg": 3.2, "faithfulness_avg": 0.9, "errors": 0}


def test_render_report_sections():
    md = report.render_report(1, INFO, summary(), JUDGES, prev=None)
    for i, title in enumerate(report.SECTIONS, start=1):
        assert f"## {i}. {title}" in md
    assert "C02" in md and "규칙 단계" in md and "abc1234" in md
    assert "❌" in md and "✅" in md


def test_render_report_compares_prev():
    prev = report.headline(summary(overall_accuracy=0.25), JUDGES)
    md = report.render_report(2, INFO, summary(), JUDGES, prev=prev)
    assert "직전 라운드" in md and "+25.0%p" in md


def test_render_report_warns_llm_errors():
    md = report.render_report(1, INFO, summary(llm_errors=4, incomplete_cases=["P01"]), JUDGES,
                              prev=None)
    assert md.index("한도/오류") < md.index("## 1.")


def test_incomplete_case_not_listed_as_wrong():
    s = summary()
    s["per_case"].append({**s["per_case"][0], "id": "G09", "correct": None, "stable": None,
                          "runs": [], "majority": None})
    md = report.render_report(1, INFO, s, JUDGES, prev=None)
    wrong = md.split("## 4.")[1].split("## 5.")[0]
    unstable = md.split("## 5.")[1].split("## 6.")[0]
    assert "G09" not in wrong and "G09" not in unstable


def test_render_report_keeps_notes():
    md = report.render_report(1, INFO, summary(), JUDGES, prev=None, notes="R1, R2 적용")
    assert md.rstrip().endswith("R1, R2 적용")
    assert report.extract_notes(md) == "R1, R2 적용"


def test_cli_exits_without_llm(monkeypatch):
    monkeypatch.setattr(run_eval.llm, "load_env", lambda *a, **k: None)
    for k in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    assert run_eval.main(["--round", "1"]) == 2
