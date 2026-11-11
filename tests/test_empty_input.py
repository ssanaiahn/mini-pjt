import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voc.db import connect, init_db, load_menus  # noqa: E402
from voc.service import get_menu_counts, process_voc  # noqa: E402


@pytest.mark.parametrize("text,rid", [
    ("", "u001"), ("   \t\n", "u001"), ("내용", ""), ("내용", "   "), ("", ""), ("  ", "  ")])
def test_ac5_blank_input_warns_and_changes_nothing(tmp_path, monkeypatch, text, rid):
    """AC5"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    conn = connect(tmp_path / "e.db")
    init_db(conn, reset=True)
    name = load_menus()[0]["name"]
    process_voc(conn, f"{name} 문의", "u001")
    hist = conn.execute("SELECT COUNT(*) FROM voc_history").fetchone()[0]
    counts = get_menu_counts(conn)

    r = process_voc(conn, text, rid)

    assert r["warnings"] and not r["input_validation"]["is_valid"]
    assert "is_processable" not in r and "matched_menus" not in r
    assert conn.execute("SELECT COUNT(*) FROM voc_history").fetchone()[0] == hist
    assert get_menu_counts(conn) == counts
    conn.close()
