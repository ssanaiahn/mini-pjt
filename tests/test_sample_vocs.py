import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voc.db import connect, init_db  # noqa: E402
from voc.service import process_voc  # noqa: E402

EXPECTED = ROOT / "data" / "sample_vocs_expected.csv"


def load_rows():
    with open(EXPECTED, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = connect(tmp_path / "test.db")
    init_db(c, reset=True)
    yield c
    c.close()


def test_sample_vocs_in_order(conn):
    rows = load_rows()
    assert len(rows) == 10
    assert any("|" in r["expected_menus"] for r in rows)
    assert any(r["expected_processable"] == "false" for r in rows)
    assert any(r["expected_frequent"] == "true" for r in rows)
    for r in rows:
        res = process_voc(conn, r["voc_text"], r["registrant_id"])
        exp_menus = [m for m in r["expected_menus"].split("|") if m]
        assert res["is_processable"] == (r["expected_processable"] == "true"), r["seq"]
        assert res["matched_menus"] == exp_menus, r["seq"]
        assert res["is_frequent"] == (r["expected_frequent"] == "true"), r["seq"]
        if not res["is_processable"]:
            assert res["guidance_draft"]
            assert res["menu_counts"] == {}
        if res["is_frequent"]:
            assert res["account_info"]["user_id"] == r["registrant_id"]
            assert res["business_data"]
            assert all(b["user_id"] == r["registrant_id"] for b in res["business_data"])


def test_unprocessable_not_counted_but_saved(conn):
    for r in load_rows():
        process_voc(conn, r["voc_text"], r["registrant_id"])
    counts = {x["menu"]: x["count"] for x in conn.execute("SELECT * FROM menu_counts")}
    assert counts == {"주문조회": 4, "배송조회": 2, "환불신청": 2,
                      "쿠폰": 1, "회원정보수정": 1}
    assert conn.execute("SELECT COUNT(*) FROM voc_history").fetchone()[0] == 10
    assert conn.execute(
        "SELECT COUNT(*) FROM voc_history WHERE is_processable=0").fetchone()[0] == 2
