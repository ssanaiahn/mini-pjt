"""라운드 리포트(마크다운) 렌더링."""
from .metrics import TARGETS

SECTIONS = ("실행 정보", "요약", "묶음별 정확도", "틀린 케이스", "불안정 케이스",
            "안내 문구 채점", "가드레일", "다음 라운드 개선 계획")
NOTES_PLACEHOLDER = "(라운드 결과를 검토한 뒤 작성)"
CATEGORY_LABELS = {"paraphrase": "표현 바꿈", "lookalike": "유사 비대상",
                   "rule_conflict": "규칙 충돌", "guardrail": "가드레일", "policy": "서비스 정책"}

# (키, 이름, 목표, 높을수록 좋음, 단위)
ROWS = [
    ("overall_accuracy", "판정 정확도 (전체)", TARGETS["overall_accuracy"], True, "pct"),
    ("agent_accuracy", "의미 판정 정확도 (표현 바꿈 + 유사 비대상)", TARGETS["agent_accuracy"], True, "pct"),
    ("false_accept", "오접수율 (처리 불가를 처리 가능으로)", TARGETS["false_accept"], False, "pct"),
    ("stability", "안정성 (3회 결과 동일)", TARGETS["stability"], True, "pct"),
    ("guardrail_pass_rate", "가드레일 준수", TARGETS["guardrail"], True, "pct"),
    ("guidance_avg", "안내 문구 품질 (LLM-as-Judge, 1~5)", TARGETS["guidance_score"], True, "score"),
    ("context_precision_avg", "검색 관련성 (RAGAS context precision)", None, True, "pct"),
    ("faithfulness_avg", "근거 충실도 (RAGAS faithfulness)", None, True, "pct"),
    ("latency_rule_max", "응답 시간: 규칙 판정 최대", TARGETS["latency_rule_s"], False, "sec"),
    ("latency_agent_avg", "응답 시간: 에이전트 판정 평균", TARGETS["latency_agent_s"], False, "sec"),
]


def headline(summary, judges):
    lat = summary.get("latency") or {}
    return {
        **{k: summary.get(k) for k in ("overall_accuracy", "agent_accuracy", "false_accept",
                                       "stability", "guardrail_pass_rate", "context_precision_avg")},
        "guidance_avg": judges.get("guidance_avg"), "faithfulness_avg": judges.get("faithfulness_avg"),
        "latency_rule_max": (lat.get("rule") or {}).get("max"),
        "latency_agent_avg": (lat.get("agent") or {}).get("avg"),
    }


def _fmt(v, unit):
    if v is None:
        return "-"
    return {"pct": f"{v * 100:.1f}%", "score": f"{v:.2f}", "sec": f"{v:.1f}s"}[unit]


def _delta(v, p, unit):
    if v is None or p is None:
        return "-"
    d = v - p
    return {"pct": f"{d * 100:+.1f}%p", "score": f"{d:+.2f}", "sec": f"{d:+.1f}s"}[unit]


def _met(v, target, higher):
    if target is None:
        return "참고"
    if v is None:
        return "-"
    return "✅" if (v >= target if higher else v <= target) else "❌"


def _out(o):
    if o is None:
        return "다수결 없음"
    processable, menus = o
    return f"처리 가능: {', '.join(menus)}" if processable else "처리 불가"


def _cell(s):
    return str(s or "-").replace("|", "\\|").replace("\n", " ")


def extract_notes(md):
    marker = f"## {len(SECTIONS)}. {SECTIONS[-1]}"
    if not md or marker not in md:
        return None
    text = md.split(marker, 1)[1].strip()
    return None if not text or text == NOTES_PLACEHOLDER else text


def render_report(round_no, info, summary, judges, prev=None, notes=None):
    h = headline(summary, judges)
    L = [f"# 라운드 {round_no} 평가 리포트", ""]
    if summary["llm_errors"] or summary["incomplete_cases"]:
        L += [f"> ⚠️ **한도/오류**: LLM 한도·오류로 대체 경로를 탄 실행이 {summary['llm_errors']}건 있습니다. "
              f"미완료 케이스: {', '.join(summary['incomplete_cases']) or '없음'}. "
              "같은 명령을 다시 실행하면 끝나지 않은 실행만 이어서 진행합니다.", ""]

    L += [f"## 1. {SECTIONS[0]}", "",
          "| 항목 | 값 |", "|---|---|",
          f"| 날짜 | {info['date']} |", f"| 모델 | `{info['model']}` |",
          f"| 케이스 수 × 반복 | {info['cases']} × {info['repeats']} |",
          f"| LangSmith 프로젝트 | `{info['langsmith_project']}` |",
          f"| 코드 버전 | `{info['commit']}` |",
          f"| RAGAS 지표 계산 | {info['ragas_method']} |", ""]

    head = "| 지표 | 결과 | 목표 | 달성 |" + (" 직전 라운드 | 변화 |" if prev else "")
    sep = "|---|---|---|---|" + ("---|---|" if prev else "")
    L += [f"## 2. {SECTIONS[1]}", "", head, sep]
    for key, label, target, higher, unit in ROWS:
        tgt = "-" if target is None else ("≥ " if higher else "≤ ") + _fmt(target, unit)
        row = f"| {label} | {_fmt(h[key], unit)} | {tgt} | {_met(h[key], target, higher)} |"
        if prev:
            row += f" {_fmt(prev.get(key), unit)} | {_delta(h[key], prev.get(key), unit)} |"
        L.append(row)
    L.append("")

    L += [f"## 3. {SECTIONS[2]}", "", "| 묶음 | 정확도 | 케이스 수 |", "|---|---|---|"]
    for cat, acc in summary["by_category"].items():
        n = sum(1 for p in summary["per_case"] if p["category"] == cat)
        L.append(f"| {CATEGORY_LABELS.get(cat, cat)} | {_fmt(acc, 'pct')} | {n} |")
    L.append("")

    wrong = [p for p in summary["per_case"] if p["correct"] is False]  # None = 미완료
    L += [f"## 4. {SECTIONS[3]}", ""]
    if wrong:
        L += ["| id | 묶음 | 입력 | 정답 | 실행 결과 | 판정 근거 | 원인 추정 |", "|---|---|---|---|---|---|---|"]
        for p in wrong:
            runs = " / ".join(_out(o) for o in p["runs"]) or "-"
            L.append(f"| {p['id']} | {CATEGORY_LABELS.get(p['category'], p['category'])} | "
                     f"{_cell(p['text'])} | {_out(p['expected'])} | {_cell(runs)} | "
                     f"{_cell(p['judge_reason'])} | {p['root_cause_hint'] or '-'} |")
    else:
        L.append("없음")
    L.append("")

    unstable = [p for p in summary["per_case"] if p["stable"] is False]
    L += [f"## 5. {SECTIONS[4]}", ""]
    if unstable:
        L += ["| id | 실행 결과 |", "|---|---|"]
        L += [f"| {p['id']} | {_cell(' / '.join(_out(o) for o in p['runs']))} |" for p in unstable]
    else:
        L.append("없음")
    L.append("")

    g = judges.get("guidance") or {}
    L += [f"## 6. {SECTIONS[5]}", "", f"평균 {_fmt(judges.get('guidance_avg'), 'score')}점 "
          f"(처리 불가로 끝난 {len(g)}건, 케이스마다 첫 실행 1건 채점)", ""]
    if g:
        L += ["| id | 점수 | 기준별 | 개선점 |", "|---|---|---|---|"]
        for cid, v in sorted(g.items(), key=lambda kv: kv[1]["overall"]):
            crit = ", ".join(f"{k} {s}" for k, s in v["scores"].items())
            L.append(f"| {cid} | {v['overall']:.2f} | {crit} | {_cell(v['comment'])} |")
        L.append("")

    L += [f"## 7. {SECTIONS[6]}", ""]
    gd = summary["guardrail_detail"]
    if gd:
        L += ["| id | 확인 항목 | 결과 |", "|---|---|---|"]
        for cid, checks in gd.items():
            for chk, ok in checks.items():
                L.append(f"| {cid} | {chk} | {'✅' if ok else '❌'} |")
    else:
        L.append("가드레일 케이스 없음")
    L += ["", f"## 8. {SECTIONS[7]}", "", notes or NOTES_PLACEHOLDER, ""]
    return "\n".join(L)
