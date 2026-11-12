"""라운드 평가 실행: python -m evaluation.run_eval --round N [--repeats 3] [--only P01,G03] [--report-only]

실제 Bedrock을 호출한다(토큰 사용). 중간에 멈추거나 한도에 걸리면 같은 명령을 다시 실행해
끝나지 않은 실행만 이어서 진행한다. 실제 data/voc.db·data/chroma는 건드리지 않는다.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from voc import llm
from voc.db import load_menus

from . import dataset, judges, metrics, report, runner

DIR = Path(__file__).resolve().parent
RESULTS = DIR / "results"


def _git_version():
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=DIR, text=True,
                              capture_output=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=DIR, text=True,
                               capture_output=True, check=True).stdout.strip()
        return f"{head} (dirty)" if dirty else head
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _prev_headline(round_no):
    p = RESULTS / f"round{round_no - 1}_summary.json"
    return json.loads(p.read_text(encoding="utf-8"))["headline"] if p.exists() else None


def main(argv=None):
    ap = argparse.ArgumentParser(description="인-아웃 세트 라운드 평가(실제 Bedrock)")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", default="", help="쉼표로 구분한 케이스 id")
    ap.add_argument("--report-only", action="store_true", help="실행 없이 기존 결과로 리포트만")
    args = ap.parse_args(argv)

    llm.load_env()
    os.environ["VOC_USE_LLM"] = "1"
    if not llm.llm_enabled():
        print("LLM을 사용할 수 없습니다: .env의 AWS 자격 증명을 확인하세요.", file=sys.stderr)
        return 2

    n = args.round
    work = RESULTS / f"round{n}_work"
    os.environ["LANGSMITH_PROJECT"] = f"voc-eval-round{n}"
    os.environ["VOC_CHROMA_PATH"] = str(work / "chroma")
    results_path = RESULTS / f"round{n}.jsonl"
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    cases = dataset.load_queries()
    if only:
        cases = [c for c in cases if c["id"] in only]
    base = runner.prepare_base(work, dataset.load_seed())
    if args.report_only:
        wanted = {c["id"] for c in cases}
        records = [r for r in runner.load_records(results_path) if r["case_id"] in wanted]
    else:
        records = runner.run_all(cases, args.repeats, n, results_path, work, base)

    registered = {m["name"] for m in load_menus()}
    summary = metrics.summarize(cases, records, args.repeats, registered)
    print("LLM 채점 중...")
    jr = judges.judge_round(cases, records, RESULTS / f"round{n}_judges.json")
    head = report.headline(summary, jr)
    (RESULTS / f"round{n}_summary.json").write_text(
        json.dumps({"headline": head, "summary": summary}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    report_path = DIR / f"round{n}_report.md"
    old = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    info = {"date": date.today().isoformat(),
            "model": os.environ.get("VOC_BEDROCK_MODEL") or llm.CHAT_MODEL,
            "region": os.environ.get("VOC_EVAL_REGION_NOTE") or llm.region(),
            "cases": len(cases), "repeats": args.repeats,
            "langsmith_project": os.environ["LANGSMITH_PROJECT"], "commit": _git_version(),
            "ragas_method": "RAGAS와 같은 정의로 직접 계산 (context precision: 정답 메뉴 기준, "
                            "faithfulness: Claude 주장 검증). ragas 패키지는 Python 3.14 미지원"}
    report_path.write_text(report.render_report(n, info, summary, jr, _prev_headline(n),
                                                report.extract_notes(old)), encoding="utf-8")
    print(f"리포트: {report_path}")
    if summary["llm_errors"] or jr["errors"]:
        print(f"주의: 한도/오류 {summary['llm_errors']}건, 채점 오류 {jr['errors']}건 → 같은 명령으로 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
