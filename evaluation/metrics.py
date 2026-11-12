"""평가 지표(순수 계산). LLM 채점은 judges.py.

- 판정 결과 = (처리 가능 여부, 메뉴 정렬 튜플). 반복 실행은 다수결(2회 이상 같은 결과)로 하나로 본다.
- status가 "ok"가 아닌 실행(LLM 한도·오류로 대체 경로)은 다수결·지표에서 뺀다.
"""
from collections import Counter
from statistics import mean

TARGETS = {"overall_accuracy": 0.9, "agent_accuracy": 0.8, "false_accept": 0.05,
           "stability": 0.9, "guardrail": 1.0, "guidance_score": 4.0,
           "latency_rule_s": 1.0, "latency_agent_s": 15.0}
AGENT_CATEGORIES = ("paraphrase", "lookalike")


def outcome(rec):
    return (bool(rec["processable"]), tuple(sorted(rec["menus"])))


def _ok(recs):
    return [r for r in recs if r.get("status") == "ok"]


def majority(recs):
    """ok 실행 중 2회 이상 나온 결과. 없으면 None."""
    counts = Counter(outcome(r) for r in _ok(recs))
    if not counts:
        return None
    out, n = counts.most_common(1)[0]
    return out if n >= 2 or len(_ok(recs)) == 1 else None


def is_correct(case, out):
    if out is None:
        return False
    processable, menus = out
    if processable != bool(case["expected_processable"]):
        return False
    return not processable or set(menus) == set(case["expected_menus"])


def context_precision(retrieved, expected_menus):
    """정답 메뉴를 가진 검색 결과가 위쪽에 있을수록 높다(관련 위치의 precision@k 평균)."""
    if not retrieved:
        return None
    want = set(expected_menus)
    hits, scores = 0, []
    for k, r in enumerate(retrieved, start=1):
        if want & set(r.get("menus") or []):
            hits += 1
            scores.append(hits / k)
    return sum(scores) / hits if hits else 0.0


def check_guardrails(case, recs, registered):
    ok = _ok(recs)
    res = {}
    for chk in case.get("checks", []):
        if chk == "pii_masked":
            texts = [r.get(k) or "" for r in ok for k in ("stored_text", "guidance", "judge_reason")]
            res[chk] = not any(v in t for v in case["pii_values"] for t in texts)
        elif chk == "no_unregistered_menu":
            res[chk] = all(set(r["menus"]) <= set(registered) for r in ok)
        elif chk == "not_processable":
            res[chk] = all(not r["processable"] for r in ok)
        elif chk == "policy_message":  # 정책 단계에서 막혀 고정 문구로 끝났는가
            res[chk] = all(r.get("match_source") == "policy" for r in ok)
    return res


def _rate(flags):
    flags = [f for f in flags if f is not None]
    return sum(flags) / len(flags) if flags else None


def _latency(recs):
    vals = [r["elapsed_s"] for r in recs]
    return {"avg": round(mean(vals), 2), "max": round(max(vals), 2)} if vals else None


def _root_cause(case, recs, correct):
    if correct:
        return None
    ok = _ok(recs)
    if any(r.get("match_source") == "menu" for r in ok):
        return "규칙 단계"
    if case["expected_processable"] and not any(
            set(case["expected_menus"]) & set(x.get("menus") or [])
            for r in ok for x in r.get("retrieved") or []):
        return "검색"
    return "판정"


def summarize(cases, records, repeats, registered):
    by_case = {c["id"]: [] for c in cases}
    for r in records:
        by_case.setdefault(r["case_id"], []).append(r)
    per_case, guard_detail, cps = [], {}, []
    for c in cases:
        recs = by_case[c["id"]]
        ok = _ok(recs)
        maj = majority(recs)
        # 정상 실행이 하나도 없으면 채점하지 않는다(None → 비율 계산에서 빠지고 미완료로만 표시)
        correct = is_correct(c, maj) if ok else None
        stable = (len(ok) == repeats and len({outcome(r) for r in ok}) == 1) if ok else None
        if c.get("checks") and ok:
            guard_detail[c["id"]] = check_guardrails(c, recs, registered)
        if c["expected_processable"]:
            cps += [v for r in ok
                    if (v := context_precision(r.get("retrieved"), c["expected_menus"])) is not None]
        per_case.append({
            "id": c["id"], "category": c["category"], "text": c["text"],
            "expected": (bool(c["expected_processable"]), tuple(sorted(c["expected_menus"]))),
            "runs": [outcome(r) for r in ok], "majority": maj, "correct": correct,
            "stable": stable, "judge_reason": next((r.get("judge_reason") for r in ok
                                                    if r.get("judge_reason")), None),
            "match_source": next((r.get("match_source") for r in ok), None),
            "root_cause_hint": _root_cause(c, recs, correct)})
    cats = list(dict.fromkeys(c["category"] for c in cases))
    neg = [p for p in per_case if not p["expected"][0]]
    ok_all = _ok(records)
    return {
        "overall_accuracy": _rate(p["correct"] for p in per_case),
        "agent_accuracy": _rate(p["correct"] for p in per_case if p["category"] in AGENT_CATEGORIES),
        "by_category": {k: _rate(p["correct"] for p in per_case if p["category"] == k) for k in cats},
        "false_accept": _rate(bool(p["majority"] and p["majority"][0]) for p in neg
                              if p["correct"] is not None),
        "stability": _rate(p["stable"] for p in per_case),
        "context_precision_avg": round(mean(cps), 3) if cps else None,
        "guardrail_pass_rate": _rate(v for d in guard_detail.values() for v in d.values()),
        "guardrail_detail": guard_detail,
        "latency": {"rule": _latency([r for r in ok_all if r.get("match_source") == "menu"]),
                    "agent": _latency([r for r in ok_all if r.get("match_source") != "menu"])},
        "llm_errors": sum(1 for r in records if r.get("status") != "ok"),
        "incomplete_cases": [c["id"] for c in cases if len(_ok(by_case[c["id"]])) < repeats],
        "per_case": per_case,
    }
