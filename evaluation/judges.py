"""LLM-as-Judge 채점 (Bedrock Claude, 구조화 출력).

- 안내 문구 품질: 처리 불가 안내 문구를 5개 기준으로 1~5점.
- 근거 충실도(RAGAS faithfulness와 같은 방법): 판정 근거를 주장 단위로 나누고, 각 주장이
  도구 결과(메뉴 목록·검색 결과)로 뒷받침되는지 판정 → 뒷받침된 주장 비율.
  ragas 패키지는 Python 3.14에서 설치되지 않아 같은 정의로 직접 계산한다.
토큰을 아끼려고 케이스마다 첫 번째 정상 실행 1건만 채점하고, 결과를 캐시 파일에 저장한다.
"""
import json
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field

METHOD = "claude"
GUIDANCE_CRITERIA = ("정중함", "처리 불가 이유", "문의처 안내", "처리 약속 없음", "개인정보 없음")
_FIELDS = ("politeness", "reason", "contact", "no_promise", "no_pii")

GUIDANCE_PROMPT = """너는 사내 VOC 답변 품질을 채점하는 평가자다.
아래 VOC는 처리 불가로 판정되었고, 담당자가 등록자에게 보낼 안내 문구 초안이 만들어졌다.
안내 문구를 다음 기준마다 1~5점(5가 가장 좋음)으로 채점하라.
- politeness(정중함): 정중하고 공손한가
- reason(처리 불가 이유): 왜 이 창구에서 처리할 수 없는지 이해할 수 있게 설명하는가
- contact(문의처 안내): 어디로 문의하면 되는지 도움을 주는가(구체적일수록 높음)
- no_promise(처리 약속 없음): 처리해 주겠다는 약속이나 사실과 다른 확언이 없는가(없을수록 높음)
- no_pii(개인정보 없음): 전화번호·이메일·주민번호 같은 개인정보가 없는가(없으면 5)
comment에는 가장 큰 개선점을 한국어 한 문장으로 쓴다."""

FAITHFULNESS_PROMPT = """너는 판정 근거의 사실성을 검증하는 평가자다.
판정 근거를 독립된 주장 단위로 나누고, 각 주장이 [도구 결과]의 내용만으로 뒷받침되는지 판정하라.
VOC 본문을 요약·인용한 주장은 [VOC]로 뒷받침되면 supported=true로 본다.
일반 상식이나 추측에 기대는 주장은 supported=false다."""


class GuidanceScore(BaseModel):
    """안내 문구 채점 결과."""
    politeness: int = Field(ge=1, le=5)
    reason: int = Field(ge=1, le=5)
    contact: int = Field(ge=1, le=5)
    no_promise: int = Field(ge=1, le=5)
    no_pii: int = Field(ge=1, le=5)
    comment: str


class Claim(BaseModel):
    text: str = Field(description="판정 근거에서 나눈 주장 하나")
    supported: bool = Field(description="도구 결과 또는 VOC로 뒷받침되면 true")


class FaithfulnessResult(BaseModel):
    """판정 근거 주장별 검증 결과."""
    claims: list[Claim]


def _model(model):
    if model is not None:
        return model
    from voc import llm
    return llm.chat_model(timeout=60, max_tokens=1000)


def score_guidance(voc_text, guidance, model=None):
    r = _model(model).with_structured_output(GuidanceScore).invoke([
        ("system", GUIDANCE_PROMPT), ("user", f"[VOC]\n{voc_text}\n\n[안내 문구]\n{guidance}")])
    scores = {label: getattr(r, f) for label, f in zip(GUIDANCE_CRITERIA, _FIELDS)}
    return {"scores": scores, "overall": round(mean(scores.values()), 2), "comment": r.comment}


def score_faithfulness(reason, contexts, model=None, voc_text=""):
    ctx = "\n---\n".join(contexts)
    r = _model(model).with_structured_output(FaithfulnessResult).invoke([
        ("system", FAITHFULNESS_PROMPT),
        ("user", f"[VOC]\n{voc_text}\n\n[도구 결과]\n{ctx}\n\n[판정 근거]\n{reason}")])
    n = len(r.claims)
    ok = sum(c.supported for c in r.claims)
    return {"score": round(ok / n, 3) if n else None, "claims": n, "supported": ok,
            "method": METHOD}


def _first_ok(records):
    by = {}
    for r in sorted(records, key=lambda r: r["repeat"]):
        if r.get("status") == "ok":
            by.setdefault(r["case_id"], r)
    return by


def judge_round(cases, records, cache_path, model=None):
    cache_path = Path(cache_path) if cache_path else None
    data = {"method": METHOD, "guidance": {}, "faithfulness": {}}
    if cache_path and cache_path.exists():
        data.update(json.loads(cache_path.read_text(encoding="utf-8")))
    texts = {c["id"]: c["text"] for c in cases}
    errors = 0
    for cid, r in _first_ok(records).items():
        if cid not in texts:
            continue
        voc = r.get("stored_text") or ""  # 개인정보를 가린 본문만 채점 모델에 보낸다
        jobs = []
        if (not r["processable"] and r.get("guidance_source") == "claude" and r.get("guidance")
                and cid not in data["guidance"]):
            jobs.append(("guidance", lambda: {**score_guidance(voc, r["guidance"], model),
                                              "guidance": r["guidance"]}))
        if r.get("judge_reason") and r.get("tool_results") and cid not in data["faithfulness"]:
            jobs.append(("faithfulness", lambda: {**score_faithfulness(
                r["judge_reason"], [t["content"] for t in r["tool_results"]], model, voc),
                "reason": r["judge_reason"]}))
        for kind, job in jobs:
            try:
                data[kind][cid] = job()
            except Exception:  # 한도·오류: 저장하지 않아 다음 실행 때 다시 채점
                errors += 1
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    g = [v["overall"] for v in data["guidance"].values()]
    f = [v["score"] for v in data["faithfulness"].values() if v["score"] is not None]
    return {**data, "guidance_avg": round(mean(g), 2) if g else None,
            "faithfulness_avg": round(mean(f), 3) if f else None, "errors": errors}
