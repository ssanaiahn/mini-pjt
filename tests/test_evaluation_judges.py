"""LLM 채점(안내 문구·근거 충실도): 가짜 모델로 계산·캐시·대상 선택 확인."""
import json

import pytest

from evaluation import judges as j


class FakeModel:
    def __init__(self):
        self.calls = []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.calls.append(self.schema.__name__)
        if self.schema is j.GuidanceScore:
            return j.GuidanceScore(politeness=5, reason=4, contact=3, no_promise=5, no_pii=5,
                                   comment="양호")
        return j.FaithfulnessResult(claims=[j.Claim(text="a", supported=True),
                                            j.Claim(text="b", supported=False)])


def test_score_guidance_overall_is_mean():
    r = j.score_guidance("문의", "안내 문구", model=FakeModel())
    assert r["scores"] == {"정중함": 5, "처리 불가 이유": 4, "문의처 안내": 3,
                           "처리 약속 없음": 5, "개인정보 없음": 5}
    assert r["overall"] == pytest.approx(4.4) and r["comment"] == "양호"


def test_score_faithfulness_ratio():
    r = j.score_faithfulness("근거", ["도구 결과"], model=FakeModel())
    assert r == {"score": 0.5, "claims": 2, "supported": 1, "method": "claude"}


def rec(cid, repeat, **kw):
    base = {"case_id": cid, "repeat": repeat, "status": "ok", "processable": False, "menus": [],
            "guidance": "안내", "guidance_source": "claude", "judge_reason": "근거",
            "tool_results": [{"name": "list_menus", "content": "[]"}], "stored_text": "본문"}
    return {**base, **kw}


CASES = [{"id": "L01", "text": "본문"}, {"id": "P01", "text": "본문2"}]


def test_judge_round_picks_first_ok_record_and_targets():
    model = FakeModel()
    records = [rec("L01", 2, guidance="두번째"), rec("L01", 1, status="llm_error"),
               rec("L01", 3, guidance="세번째"),
               rec("P01", 1, processable=True, menus=["보안 신고"], guidance=None,
                   guidance_source=None, tool_results=[])]
    out = j.judge_round(CASES, records, None, model=model)
    assert set(out["guidance"]) == {"L01"}  # 처리 가능 건은 안내 문구 채점 안 함
    assert out["guidance"]["L01"]["guidance"] == "두번째"  # ok 중 가장 앞 반복
    assert set(out["faithfulness"]) == {"L01"}  # 도구 결과 없는 건은 충실도 채점 안 함
    assert out["guidance_avg"] == pytest.approx(4.4) and out["faithfulness_avg"] == 0.5


def test_judge_round_uses_cache(tmp_path):
    cache = tmp_path / "judges.json"
    j.judge_round(CASES, [rec("L01", 1)], cache, model=FakeModel())
    again = FakeModel()
    out = j.judge_round(CASES, [rec("L01", 1)], cache, model=again)
    assert again.calls == [] and out["guidance"]["L01"]["overall"] == pytest.approx(4.4)
    assert json.loads(cache.read_text(encoding="utf-8"))["method"] == "claude"


def test_judge_round_skips_failed_scoring(tmp_path):
    class Broken(FakeModel):
        def invoke(self, messages):
            raise RuntimeError("throttled")
    out = j.judge_round(CASES, [rec("L01", 1)], tmp_path / "c.json", model=Broken())
    assert out["guidance"] == {} and out["errors"] == 2
    assert out["error_messages"][0].startswith("L01 guidance: RuntimeError: throttled")
