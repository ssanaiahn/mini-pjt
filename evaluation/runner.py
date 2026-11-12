"""평가 실행: 기준 DB(과거 이력) 준비 → 케이스 × 반복마다 새 DB 복사본에서 run_voc 실행.

- 케이스끼리 이력·누적이 섞이지 않도록 실행마다 기준 DB를 복사한다.
- 결과는 jsonl에 한 줄씩 추가하고, 다시 실행하면 이미 성공한 (케이스, 반복)은 건너뛴다.
- LLM 한도·오류로 대체 경로를 탄 실행은 status="llm_error"로 표시해 정답 비교에서 뺀다.
"""
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from voc.db import connect, init_db
from voc.graph import run_voc

LLM_ERROR_GUIDANCE = ("template_error", "template_timeout")


def prepare_base(workdir, seed_rows):
    """workdir/base.db: 모의 데이터 + 과거 이력(규칙 모드로 저장 → match_source='menu')."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    base = workdir / "base.db"
    if base.exists():
        return base
    conn = connect(base)
    try:
        init_db(conn, reset=True)
        for row in seed_rows:
            run_voc(conn, row["text"], row["registrant_id"], use_api=False)
    finally:
        conn.close()
    return base


@contextmanager
def _env(key, value):
    old = os.environ.get(key)
    os.environ[key] = str(value)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _trace(case, repeat, round_no):
    from langsmith import tracing_context

    return tracing_context(project_name=f"voc-eval-round{round_no}",
                           tags=[case["id"], case["category"]],
                           metadata={"case_id": case["id"], "repeat": repeat, "round": round_no})


def _stored_text(conn, result):
    if result.get("voc_id"):
        row = conn.execute("SELECT voc_text FROM voc_history WHERE id=?",
                           (result["voc_id"],)).fetchone()
        if row:
            return row[0]
    return result.get("voc_text")


def run_case(base_db, workdir, case, repeat, round_no):
    """케이스 1건 × 반복 1회 실행 → 기록 dict."""
    run_db = Path(workdir) / "run.db"
    shutil.copyfile(base_db, run_db)
    with _env("VOC_DB_PATH", run_db):  # MCP 서버·검색 도구도 이 복사본을 본다
        conn = connect(run_db)
        try:
            t0 = time.perf_counter()
            with _trace(case, repeat, round_no):
                r = run_voc(conn, case["text"], case["registrant_id"], use_api=True)
            elapsed = time.perf_counter() - t0
            stored = _stored_text(conn, r)
        finally:
            conn.close()
    run_db.unlink(missing_ok=True)
    judge = r.get("judge") or {}
    error = bool(r.get("agent_error")) or r.get("guidance_source") in LLM_ERROR_GUIDANCE
    return {
        "case_id": case["id"], "repeat": repeat, "status": "llm_error" if error else "ok",
        "processable": bool(r.get("is_processable")), "menus": r.get("matched_menus") or [],
        "match_source": r.get("match_source"), "agent_error": r.get("agent_error"),
        "judge_reason": judge.get("reason"), "judge_menus_raw": judge.get("menus"),
        "tool_calls": judge.get("tool_calls") or [], "tool_results": judge.get("tool_results") or [],
        "retrieved": judge.get("retrieved") or [], "guidance": r.get("guidance_draft"),
        "guidance_source": r.get("guidance_source"), "pii_found": r.get("pii_found") or [],
        "stored_text": stored, "elapsed_s": round(elapsed, 2),
    }


def load_records(results_path):
    """jsonl에서 (case_id, repeat)마다 마지막 기록."""
    path = Path(results_path)
    latest = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[(rec["case_id"], rec["repeat"])] = rec
    return list(latest.values())


def run_all(cases, repeats, round_no, results_path, workdir, base_db, only=None, progress=print):
    """아직 성공하지 못한 (케이스, 반복)만 실행하고, 대상 케이스의 최신 기록을 돌려준다."""
    results_path = Path(results_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    targets = [c for c in cases if not only or c["id"] in only]
    done = {(r["case_id"], r["repeat"]): r for r in load_records(results_path)}
    todo = [(c, i) for c in targets for i in range(1, repeats + 1)
            if done.get((c["id"], i), {}).get("status") != "ok"]
    for n, (case, i) in enumerate(todo, start=1):
        rec = run_case(base_db, workdir, case, i, round_no)
        with open(results_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done[(case["id"], i)] = rec
        progress(f"[{n}/{len(todo)}] {case['id']} #{i} → {rec['status']} "
                 f"{'처리 가능 ' + ','.join(rec['menus']) if rec['processable'] else '처리 불가'}"
                 f" ({rec['elapsed_s']}s)")
    return [done[(c["id"], i)] for c in targets for i in range(1, repeats + 1)
            if (c["id"], i) in done]
