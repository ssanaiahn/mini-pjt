import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import voc.db  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    real_connect = voc.db.connect
    monkeypatch.setattr(voc.db, "connect", lambda *a, **k: real_connect(tmp_path / "app.db"))
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def submit(at, text, rid):
    at.text_area[0].set_value(text)
    at.text_input[0].set_value(rid)
    return at.button[0].click().run()


def test_ac3_processable_shown(app):
    """AC3"""
    name = voc.db.load_menus()[0]["name"]
    at = submit(app, f"{name} 문의", "u001")
    assert not at.exception
    assert any("처리 가능" in s.value for s in at.success)


def test_ac3_unprocessable_shown_with_guidance(app):
    """AC3"""
    at = submit(app, "zzqq 등록되지 않은 내용", "u001")
    assert not at.exception
    assert any("처리 불가" in e.value for e in at.error)
    assert at.text_area[-1].value


def test_ac5_empty_input_warns(app):
    """AC3"""
    at = submit(app, "   ", "u001")
    assert not at.exception
    assert at.warning
    at = submit(app, "내용", "  ")
    assert at.warning


def test_ac3_frequent_unknown_registrant_shows_not_found(app):
    """AC3"""
    name = voc.db.load_menus()[0]["name"]
    at = app
    for _ in range(3):
        at = submit(at, f"{name} 문의", "nobody")
        assert not at.exception
    assert any("등록자 정보 없음" in w.value for w in at.warning)


def test_ac3_menu_config_failure_shows_error(tmp_path, monkeypatch):
    """AC3"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    real_connect = voc.db.connect
    monkeypatch.setattr(voc.db, "connect", lambda *a, **k: real_connect(tmp_path / "app.db"))
    monkeypatch.setattr(voc.db, "MENUS_PATH", tmp_path / "missing.json")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert at.error
    assert not at.button
    assert not (tmp_path / "app.db").exists()


# ---- 환경 변수 기반 AppTest (monkeypatch 없이 첫 실행 상태) ----
def _env_app(tmp_path, monkeypatch, menus_path=None):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db = tmp_path / "sub" / "env.db"
    monkeypatch.setenv("VOC_DB_PATH", str(db))
    if menus_path is not None:
        monkeypatch.setenv("VOC_MENUS_PATH", str(menus_path))
    return db, AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def test_ac3_env_first_run_creates_db_and_shows_verdict(tmp_path, monkeypatch):
    db, at = _env_app(tmp_path, monkeypatch)
    at = submit(at, f"{voc.db.load_menus()[0]['name']} 문의", "u001")
    assert not at.exception
    assert any("처리 가능" in s.value for s in at.success)
    at = submit(at, "zzqq 내용", "u001")
    assert not at.exception
    assert any("처리 불가" in e.value for e in at.error)
    assert db.exists()


def test_ac3_env_frequent_unknown_registrant(tmp_path, monkeypatch):
    db, at = _env_app(tmp_path, monkeypatch)
    for _ in range(3):
        at = submit(at, f"{voc.db.load_menus()[0]['name']} 문의", "nobody")
        assert not at.exception
    assert any("등록자 정보 없음" in w.value for w in at.warning)
    assert any("업무 데이터" in h.value for h in at.subheader)
    assert any("조회된 업무 데이터가 없습니다" in m.value for m in at.markdown)


@pytest.mark.parametrize("kind", ["missing", "dup"])
def test_ac3_env_bad_menu_config_blocks(tmp_path, monkeypatch, kind):
    if kind == "missing":
        path = tmp_path / "nope.json"
    else:
        path = tmp_path / "dup.json"
        path.write_text('{"menus":[{"name":"A","aliases":["x"]},{"name":"B","aliases":["X"]}]}',
                        encoding="utf-8")
    db, at = _env_app(tmp_path, monkeypatch, path)
    assert not at.exception
    assert at.error
    assert not at.button
    assert not db.exists()
