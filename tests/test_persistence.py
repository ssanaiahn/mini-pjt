import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voc.db import connect, init_db  # noqa: E402
from voc.service import process_voc  # noqa: E402


def test_history_and_counts_survive_reopen(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db = tmp_path / "persist.db"
    conn = connect(db)
    init_db(conn, reset=True)
    from voc.db import load_menus
    menus = load_menus()
    name = menus[0]["name"]
    r1 = process_voc(conn, f"{name} 관련 문의입니다", "u001")
    r2 = process_voc(conn, f"{name} 또 문의", "u002")
    r3 = process_voc(conn, "zzqq 등록되지 않은 내용 xyzxyz", "u001")
    assert r1["is_processable"] and r2["is_processable"]
    assert not r3["is_processable"] and r3["guidance_draft"]
    conn.close()

    # 같은 파일을 다시 열고 init_db(reset 없이)로 앱 재시작을 모사
    conn2 = connect(db)
    init_db(conn2)
    hist = conn2.execute("SELECT * FROM voc_history ORDER BY id").fetchall()
    assert len(hist) == 3
    assert [h["is_processable"] for h in hist] == [1, 1, 0]
    assert hist[2]["guidance_draft"]
    counts = {r["menu"]: r["count"] for r in conn2.execute("SELECT * FROM menu_counts")}
    assert counts == {name: 2}  # 처리 불가 건은 누적 제외
    # 재시작 후 이어서 누적
    r4 = process_voc(conn2, f"{name} 세번째", "u003")
    assert r4["menu_counts"][name] == 3 and r4["is_frequent"]
    conn2.close()
