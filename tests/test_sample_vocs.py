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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-ignored")  # 원래 키가 있던 환경 가정
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("VOC_DB_PATH", str(tmp_path / "test.db"))
    c = connect()  # 앱과 같은 환경변수 기반 경로
    init_db(c, reset=True)
    yield c
    c.close()


def split(v):
    return [x for x in v.split("|") if x]


def parse_counts(v):
    return {k: int(n) for k, n in (x.split(":") for x in split(v))}


def test_ac1_unknown_registrant_frequent(conn):
    """AC1"""
    for _ in range(3):
        res = process_voc(conn, "주문조회 문의", "nobody", use_api=False)
    assert res["is_frequent"]
    assert res["account_info"]["found"] is False
    assert res["account_info"]["account"] is None
    assert res["business_data"] == []


def test_ac1_sample_vocs_in_order(conn):
    """AC1"""
    rows = load_rows()
    assert len(rows) == 10
    assert any("|" in r["expected_menus"] for r in rows)
    assert any(r["expected_processable"] == "false" for r in rows)
    assert any(r["expected_frequent"] == "true" for r in rows)
    for r in rows:
        res = process_voc(conn, r["voc_text"], r["registrant_id"], use_api=False)
        seq = r["seq"]
        assert res["is_processable"] == (r["expected_processable"] == "true"), seq
        assert res["matched_menus"] == split(r["expected_menus"]), seq
        assert res["count_snapshot"] == parse_counts(r["expected_counts"]), seq
        assert res["is_frequent"] == (r["expected_frequent"] == "true"), seq
        assert res["frequent_menus"] == split(r["expected_lookup_menus"]), seq
        if not res["is_processable"]:
            assert res["guidance_draft"]
            assert res["guidance_source"] == "template_no_key"
            assert res["count_snapshot"] == {}
        if res["is_frequent"]:
            assert res["account_info"]["found"] is True
            assert res["account_info"]["account"]["user_id"] == r["registrant_id"]
            assert res["business_data"]
            assert {b["menu"] for b in res["business_data"]} == set(res["frequent_menus"])
            assert all(b["user_id"] == r["registrant_id"] for b in res["business_data"])
        else:
            assert res["account_info"] is None and res["business_data"] == []


def test_ac1_expected_table_composition():
    from voc.db import load_menus, normalize

    rows = load_rows()
    menus = load_menus()
    tags = {r["seq"]: set(split(r["case_tags"])) for r in rows}
    allt = set().union(*tags.values())
    assert {"multi_menu", "unprocessable", "reach_3"} <= allt
    assert allt & {"overlap_alias", "spacing"}
    for r in rows:
        t = tags[r["seq"]]
        if "multi_menu" in t:
            assert len(split(r["expected_menus"])) >= 2
        if "unprocessable" in t:
            assert r["expected_processable"] == "false"
        if "reach_3" in t:
            assert 3 in parse_counts(r["expected_counts"]).values()
        if "spacing" in t:
            terms = [x for m in menus for x in [m["name"], *m.get("aliases", [])]]
            body = r["voc_text"]
            assert not [x for x in terms if x in body]
            nospace = "".join(body.split())
            assert [x for x in terms if "".join(x.split()) in nospace]


def test_ac1_unprocessable_not_counted_but_saved(conn):
    """AC1"""
    for r in load_rows():
        process_voc(conn, r["voc_text"], r["registrant_id"])
    counts = {x["menu"]: x["count"] for x in conn.execute("SELECT * FROM menu_counts")}
    assert counts == {"주문조회": 4, "배송조회": 2, "환불신청": 2,
                      "쿠폰": 1, "회원정보수정": 1}
    assert conn.execute("SELECT COUNT(*) FROM voc_history").fetchone()[0] == 10
    assert conn.execute(
        "SELECT COUNT(*) FROM voc_history WHERE is_processable=0").fetchone()[0] == 2
