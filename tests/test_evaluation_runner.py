"""평가 실행기: 임시 DB 복사, 오류 표시, 이어서 실행 (Bedrock 미호출: run_voc를 가짜로)."""
import json
import os

import pytest

from evaluation import runner
from voc.db import connect

CASE = {"id": "P01", "category": "paraphrase", "text": "이상한 메일", "registrant_id": "u001"}


def fake_result(**kw):
    base = {"is_processable": True, "matched_menus": ["보안 신고"], "match_source": "agent",
            "judge": {"reason": "피싱", "menus": ["보안 신고"], "tool_calls": ["list_menus"],
                      "tool_results": [{"name": "list_menus", "content": "[]"}],
                      "retrieved": [{"id": 1, "voc_text": "x", "menus": ["보안 신고"],
                                     "similarity": 0.7}]},
            "agent_error": None, "guidance_draft": None, "guidance_source": None,
            "pii_found": [], "voc_text": "이상한 메일", "voc_id": None}
    return {**base, **kw}


@pytest.fixture
def base(tmp_path):
    return runner.prepare_base(tmp_path, [
        {"text": "보안 신고 합니다", "registrant_id": "u001", "menus": ["보안 신고"]},
        {"text": "사용자 권한 요청", "registrant_id": "u002", "menus": ["사용자 관리"]}])


def rows(db):
    c = connect(db)
    try:
        return c.execute("SELECT match_source FROM voc_history").fetchall()
    finally:
        c.close()


def test_prepare_base_seeds_menu_history(base):
    assert [r[0] for r in rows(base)] == ["menu", "menu"]


def test_run_case_uses_fresh_copy(tmp_path, base, monkeypatch):
    seen = []

    def fake(conn, text, rid, use_api=True):
        seen.append((os.environ["VOC_DB_PATH"], use_api))
        conn.execute("DELETE FROM voc_history")
        conn.commit()
        return fake_result()
    monkeypatch.setattr(runner, "run_voc", fake)
    r1 = runner.run_case(base, tmp_path, CASE, 1, round_no=1)
    runner.run_case(base, tmp_path, CASE, 2, round_no=1)
    assert len(rows(base)) == 2  # 기준 DB는 그대로
    assert all(p.endswith("run.db") and api for p, api in seen)
    assert r1["status"] == "ok" and r1["menus"] == ["보안 신고"]
    assert r1["retrieved"][0]["id"] == 1 and r1["judge_reason"] == "피싱"
    assert r1["stored_text"] == "이상한 메일" and r1["elapsed_s"] >= 0


@pytest.mark.parametrize("kw", [{"agent_error": "ThrottlingException: limit"},
                                {"guidance_source": "template_timeout"}])
def test_run_case_marks_llm_error(tmp_path, base, monkeypatch, kw):
    monkeypatch.setattr(runner, "run_voc", lambda *a, **k: fake_result(**kw))
    assert runner.run_case(base, tmp_path, CASE, 1, round_no=1)["status"] == "llm_error"


def test_run_all_resumes(tmp_path, base, monkeypatch):
    results = tmp_path / "r.jsonl"
    results.write_text("\n".join(json.dumps(r) for r in [
        {"case_id": "P01", "repeat": 1, "status": "ok"},
        {"case_id": "P01", "repeat": 2, "status": "llm_error"}]) + "\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "run_voc",
                        lambda c, t, rid, use_api=True: calls.append(t) or fake_result())
    out = runner.run_all([CASE], 2, 1, results, tmp_path, base, progress=lambda *a: None)
    assert len(calls) == 1
    assert [(r["repeat"], r["status"]) for r in out] == [(1, "ok"), (2, "ok")]
    assert len(results.read_text(encoding="utf-8").splitlines()) == 3  # 추가만 함


def test_run_all_only_filter(tmp_path, base, monkeypatch):
    monkeypatch.setattr(runner, "run_voc", lambda *a, **k: fake_result())
    other = {**CASE, "id": "L01"}
    out = runner.run_all([CASE, other], 1, 1, tmp_path / "r.jsonl", tmp_path, base,
                         only={"L01"}, progress=lambda *a: None)
    assert [r["case_id"] for r in out] == ["L01"]
