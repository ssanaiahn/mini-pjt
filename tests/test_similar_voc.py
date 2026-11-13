"""메뉴명이 없을 때 과거 VOC 유사도로 보완 판정."""
import sqlite3

import pytest

from src.shared.db import connect, init_db
from src.retrieval.lexical import SIMILARITY_THRESHOLD
from src.shared.text import similarity


MENUS = [
    {"name": "주문조회", "aliases": ["주문내역"]},
    {"name": "배송조회", "aliases": ["배송현황"]},
    {"name": "쿠폰", "aliases": ["할인쿠폰"]},
]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = connect(tmp_path / "t.db")
    init_db(c, reset=True, menus=MENUS)
    yield c
    c.close()


def process_voc(conn, text, rid, **kw):
    from src.workflows.voc_graph import process_voc as real
    return real(conn, text, rid, menus=MENUS, **kw)


def test_similarity_basics():
    assert similarity("주문내역이 안 보여요", "주문내역이안보여요") == 1.0
    assert similarity("오늘 날씨 어때요", "주문내역이 안 보여요") < SIMILARITY_THRESHOLD
    assert similarity("", "주문") == 0.0


def test_similar_voc_borrows_menus(conn):
    first = process_voc(conn, "쿠폰 적용이 결제 화면에서 안 돼요", "u001", use_api=False)
    assert first["match_source"] == "menu"
    res = process_voc(conn, "할인 적용이 결제 화면에서 안 돼요", "u002", use_api=False)
    assert res["is_processable"] is True
    assert res["match_source"] == "similar"
    assert res["matched_menus"] == ["쿠폰"]
    assert res["similar_voc"]["id"] == first["voc_id"]
    assert res["similar_voc"]["similarity"] >= SIMILARITY_THRESHOLD
    assert res["count_snapshot"] == {"쿠폰": 2}  # 유사 판정 건도 누적에 포함
    row = conn.execute("SELECT match_source, similar_voc_id FROM voc_history WHERE id=?",
                       (res["voc_id"],)).fetchone()
    assert tuple(row) == ("similar", first["voc_id"])


def test_typo_matches_past_voc(conn):
    process_voc(conn, "주문내역이 안 보여요", "u001", use_api=False)
    res = process_voc(conn, "주뮨내역이 안 보여요", "u001", use_api=False)
    assert res["matched_menus"] == ["주문조회"] and res["match_source"] == "similar"


def test_dissimilar_stays_unprocessable(conn):
    process_voc(conn, "주문내역이 안 보여요", "u001", use_api=False)
    res = process_voc(conn, "배송이 안 보여요", "u002", use_api=False)  # 어미만 같음
    assert res["is_processable"] is False
    assert res["match_source"] is None and res["similar_voc"] is None
    assert res["guidance_draft"]


def test_no_chaining_from_similar_matches(conn):
    process_voc(conn, "쿠폰 적용이 결제 화면에서 안 돼요", "u001", use_api=False)
    process_voc(conn, "할인 적용이 결제 화면에서 안 돼요", "u001", use_api=False)
    # 2번째 건(유사 판정, 0.62)과만 비슷하고 원본(0.44)과는 기준 미만인 문장
    res = process_voc(conn, "할인 적용이 결제 단계에서 안 돼요", "u001", use_api=False)
    assert res["is_processable"] is False and res["similar_voc"] is None


def test_unprocessable_history_not_used(conn):
    process_voc(conn, "점심 메뉴 추천해 주세요", "u005", use_api=False)
    res = process_voc(conn, "점심 메뉴 추천해 주세요", "u005", use_api=False)
    assert res["is_processable"] is False


def test_migrates_old_db(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE voc_history(id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " registrant_id TEXT NOT NULL, voc_text TEXT NOT NULL,"
                " is_processable INTEGER NOT NULL, matched_menus TEXT NOT NULL,"
                " guidance_draft TEXT, guidance_source TEXT, created_at TEXT NOT NULL)")
    raw.execute("INSERT INTO voc_history(registrant_id, voc_text, is_processable,"
                " matched_menus, created_at) VALUES ('u001','주문내역이 안 보여요',1,"
                "'주문조회','2026-11-10T00:00:00Z')")
    raw.commit()
    raw.close()
    c = connect(path)
    init_db(c, menus=MENUS)
    res = process_voc(c, "주뮨내역이 안 보여요", "u001", use_api=False)
    assert res["matched_menus"] == ["주문조회"] and res["similar_voc"]["id"] == 1
    c.close()
