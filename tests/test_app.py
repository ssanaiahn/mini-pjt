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


def test_processable_shown(app):
    name = voc.db.load_menus()[0]["name"]
    at = submit(app, f"{name} 문의", "u001")
    assert not at.exception
    assert any("처리 가능" in s.value for s in at.success)


def test_unprocessable_shown_with_guidance(app):
    at = submit(app, "zzqq 등록되지 않은 내용", "u001")
    assert not at.exception
    assert any("처리 불가" in e.value for e in at.error)
    assert at.text_area[-1].value


def test_empty_input_warns(app):
    at = submit(app, "   ", "u001")
    assert not at.exception
    assert at.warning
    at = submit(app, "내용", "  ")
    assert at.warning
