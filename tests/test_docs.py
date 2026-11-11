import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLS = ["seq", "registrant_id", "voc_text", "expected_processable", "expected_menus",
        "expected_counts", "expected_frequent", "expected_lookup_menus", "case_tags"]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_ac4_readme_contents():
    """AC4"""
    t = read("README.md")
    for s in ["pip install -r requirements.txt", "streamlit run", "ANTHROPIC_API_KEY", "pytest"]:
        assert s in t


def test_ac4_service_sections():
    """AC4"""
    import re
    t = read("SERVICE.md")
    for h in [r"^#{1,6}\s*판정 규칙", r"^#{1,6}\s*데이터 구조"]:
        assert re.search(h, t, re.M)


def test_ac4_expected_table():
    """AC4"""
    with open(ROOT / "data/sample_vocs_expected.csv", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        rows = list(r)
        assert all(c in r.fieldnames for c in COLS)
    assert len(rows) == 10


def test_ac4_claude_md():
    """AC4"""
    t = read("CLAUDE.md")
    assert "VOC" in t
    assert "Specification-First AI Development" not in t


def test_ac4_requirements():
    """AC4"""
    t = read("requirements.txt").lower()
    for s in ["streamlit", "anthropic", "pytest"]:
        assert s in t
