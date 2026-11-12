import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voc.db import connect, init_db, load_menus  # noqa: E402
from voc.service import get_menu_counts, process_voc  # noqa: E402


def _snapshot(conn):
    rows = conn.execute(
        "SELECT id, voc_text, registrant_id, is_processable, matched_menus, "
        "guidance_draft, guidance_source, created_at FROM voc_history ORDER BY id").fetchall()
    return [
        {"id": r["id"], "voc_text": r["voc_text"], "registrant_id": r["registrant_id"],
         "is_processable": r["is_processable"], "matched_menus": r["matched_menus"],
         "has_guidance": bool(r["guidance_draft"]),
         "guidance_source": r["guidance_source"], "created_at": r["created_at"]}
        for r in rows]


def _n(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def after_order(conn):
    return [r["matched_menus"] for r in conn.execute(
        "SELECT matched_menus FROM voc_history ORDER BY id")]


def test_ac2_history_and_counts_survive_reopen(tmp_path, monkeypatch):
    """AC2"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db = tmp_path / "persist.db"
    monkeypatch.setenv("VOC_DB_PATH", str(db))
    menus = load_menus()
    a, b = menus[0]["name"], menus[1]["name"]

    conn = connect()  # 앱과 같은 생성 함수, 경로는 환경 변수
    init_db(conn, reset=True)
    r1 = process_voc(conn, f"{a} 관련 문의입니다", "u001")
    r2 = process_voc(conn, f"{a} 와 {b} 같이 문의", "u002")
    r3 = process_voc(conn, "zzqq 등록되지 않은 내용 xyzxyz", "u001")
    r4 = process_voc(conn, f"{a} 또 문의", "u003")
    assert [r["is_processable"] for r in (r1, r2, r3, r4)] == [True, True, False, True]
    assert r3["guidance_draft"] and r1["guidance_draft"] is None
    assert set(r2["matched_menus"]) == {a, b}

    before_hist = _snapshot(conn)
    before_counts = get_menu_counts(conn)
    before_matches = conn.execute(
        "SELECT voc_id, menu FROM voc_menu_matches ORDER BY rowid").fetchall()
    before_matches = [tuple(r) for r in before_matches]
    before_sizes = {t: _n(conn, t) for t in ("voc_history", "users", "business_data")}
    assert before_counts == {a: 3, b: 1}  # 처리 불가 건 제외
    conn.close()

    conn2 = connect()  # 같은 환경 변수로 다시 열기 (reset 없음)
    init_db(conn2)
    assert {t: _n(conn2, t) for t in before_sizes} == before_sizes
    assert before_sizes["voc_history"] == 4
    assert [tuple(r) for r in conn2.execute(
        "SELECT voc_id, menu FROM voc_menu_matches ORDER BY rowid")] == before_matches
    assert after_order(conn2)[1] == f"{a}|{b}"
    after_hist = _snapshot(conn2)
    assert after_hist == before_hist
    assert len(after_hist) == 4
    assert [h["has_guidance"] for h in after_hist] == [False, False, True, False]
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    assert all(iso.match(h["created_at"]) for h in after_hist)
    assert [h["created_at"] for h in after_hist] == [h["created_at"] for h in before_hist]
    assert [h["guidance_source"] for h in after_hist] == [None, None, "template_no_key", None]
    assert after_hist[2]["matched_menus"] == ""
    assert get_menu_counts(conn2) == before_counts
    conn2.close()


def test_init_db_backfills_new_mock_users(tmp_path, monkeypatch):
    """기존 DB(u001~u006만 있음)를 다시 열면 새로 추가된 모의 사용자와 업무 데이터만 채운다."""
    monkeypatch.setenv("VOC_DB_PATH", str(tmp_path / "old.db"))
    conn = connect()
    init_db(conn)
    old = ("u001", "u002", "u003", "u004", "u005", "u006")
    qs = ",".join("?" * len(old))
    conn.execute(f"DELETE FROM users WHERE user_id NOT IN ({qs})", old)
    conn.execute(f"DELETE FROM business_data WHERE user_id NOT IN ({qs})", old)
    conn.execute("INSERT INTO voc_history(registrant_id, voc_text, is_processable, matched_menus,"
                 " created_at) VALUES ('나라바', '서약서 체결 현황', 1, '비밀유지계약', 't')")
    conn.commit()
    init_db(conn)
    users = {r[0] for r in conn.execute("SELECT user_id FROM users")}
    assert {"u001", "나라바", "가나다", "abc", "def", "ghi", "aaa", "다나가", "아차파"} <= users
    assert len(users) == 33  # u001~u006 + 앱 테스트 등록자 7명 + 추가 20명
    n_menus = len(load_menus())
    assert _n_where(conn, "business_data", "user_id='나라바'") == n_menus
    assert _n(conn, "voc_history") == 1  # 이력은 그대로
    sizes = {t: _n(conn, t) for t in ("users", "business_data")}
    init_db(conn)
    assert {t: _n(conn, t) for t in sizes} == sizes  # 두 번째부터는 아무것도 추가 안 함
    conn.close()


def _n_where(conn, table, where):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def test_ac2_reopen_twice_keeps_row_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("VOC_DB_PATH", str(tmp_path / "again.db"))
    conn = connect()
    init_db(conn)
    sizes = {t: _n(conn, t) for t in ("voc_history", "users", "business_data")}
    conn.close()
    for _ in range(2):
        c = connect()
        init_db(c)
        assert {t: _n(c, t) for t in sizes} == sizes
        c.close()
