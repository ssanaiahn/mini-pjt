"""라운드 리포트 렌더링과 CLI 진입 조건(네트워크 없음)."""
from evaluation import report, run_eval

INFO = {"date": "2026-11-12", "model": "m", "region": "us-west-2", "cases": 2, "repeats": 3,
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
    assert "C02" in md and "규칙 단계" in md and "abc1234" in md and "us-west-2" in md
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


def _no_llm(monkeypatch):
    monkeypatch.setattr(run_eval.llm, "load_env", lambda *a, **k: None)
    for k in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)


def test_cli_defaults_to_us_west_2(monkeypatch):
    """강의 안내: 평가는 us-west-2에서(공용 계정 한도 분산). 앱의 .env 리전과 별개."""
    _no_llm(monkeypatch)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("VOC_EVAL_REGION", raising=False)
    run_eval.main(["--round", "1"])
    assert run_eval.os.environ["AWS_DEFAULT_REGION"] == "us-west-2"


def test_cli_region_override(monkeypatch):
    _no_llm(monkeypatch)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("VOC_EVAL_REGION", "ap-northeast-2")
    run_eval.main(["--round", "1"])
    assert run_eval.os.environ["AWS_DEFAULT_REGION"] == "ap-northeast-2"


def test_cli_pins_eval_model_over_env(monkeypatch):
    """앱용 .env 모델(VOC_BEDROCK_MODEL)이 바뀌어도 평가는 라운드 간 같은 모델로 고정."""
    _no_llm(monkeypatch)
    monkeypatch.setenv("VOC_BEDROCK_MODEL", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
    monkeypatch.delenv("VOC_EVAL_MODEL", raising=False)
    run_eval.main(["--round", "1"])
    assert run_eval.os.environ["VOC_BEDROCK_MODEL"] == run_eval.llm.CHAT_MODEL
    monkeypatch.setenv("VOC_EVAL_MODEL", "m2")
    run_eval.main(["--round", "1"])
    assert run_eval.os.environ["VOC_BEDROCK_MODEL"] == "m2"


def test_cli_exits_without_llm(monkeypatch):
    monkeypatch.setattr(run_eval.llm, "load_env", lambda *a, **k: None)
    for k in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    assert run_eval.main(["--round", "1"]) == 2


def test_only_reruns_subset_but_reports_all_cases(monkeypatch, tmp_path):
    """--only는 실행 대상만 고르고, 요약·리포트는 라운드 전체 케이스로 만든다(최종 리뷰 #6)."""
    import json
    cases = [{"id": "P01", "category": "paraphrase", "text": "a", "expected_processable": False,
              "expected_menus": [], "checks": [], "pii_values": []},
             {"id": "L01", "category": "lookalike", "text": "b", "expected_processable": False,
              "expected_menus": [], "checks": [], "pii_values": []}]
    recs = [{"case_id": c["id"], "repeat": 1, "status": "ok", "processable": False, "menus": [],
             "match_source": None, "retrieved": [], "elapsed_s": 1.0} for c in cases]
    ran = {}
    monkeypatch.setattr(run_eval.llm, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(run_eval.llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(run_eval, "RESULTS", tmp_path)
    monkeypatch.setattr(run_eval, "DIR", tmp_path)
    monkeypatch.setattr(run_eval, "_git_version", lambda: "x")
    monkeypatch.setattr(run_eval.dataset, "load_queries", lambda: cases)
    monkeypatch.setattr(run_eval.dataset, "load_seed", lambda: [])
    monkeypatch.setattr(run_eval.runner, "prepare_base", lambda *a: tmp_path / "base.db")
    monkeypatch.setattr(run_eval.runner, "run_all",
                        lambda cs, *a, **k: ran.setdefault("ids", [c["id"] for c in cs]) and [])
    monkeypatch.setattr(run_eval.runner, "load_records", lambda p: recs)
    monkeypatch.setattr(run_eval.judges, "judge_round", lambda *a, **k: {
        "guidance": {}, "faithfulness": {}, "guidance_avg": None, "faithfulness_avg": None,
        "errors": 0, "error_messages": []})
    for k in ("VOC_USE_LLM", "AWS_DEFAULT_REGION", "LANGSMITH_PROJECT", "VOC_CHROMA_PATH"):
        monkeypatch.setenv(k, "x")
    assert run_eval.main(["--round", "1", "--repeats", "1", "--only", "L01"]) == 0
    assert ran["ids"] == ["L01"]
    summary = json.loads((tmp_path / "round1_summary.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in summary["summary"]["per_case"]] == ["P01", "L01"]
