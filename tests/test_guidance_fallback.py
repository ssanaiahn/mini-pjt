import socket
import sys
import types
from pathlib import Path

import anthropic
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voc import guidance  # noqa: E402


@pytest.fixture(autouse=True)
def block_sockets(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


def _mock_client(monkeypatch, create):
    """anthropic.Anthropic을 모의 객체로 교체. (생성 횟수, create 호출 기록) 반환."""
    state = {"created": 0, "calls": []}

    def recording_create(*args, **kw):
        state["calls"].append((args, kw))
        return create(*args, **kw)

    class Client:
        def __init__(self, **kw):
            state["created"] += 1
            self.messages = types.SimpleNamespace(create=recording_create)

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    return state


def test_ac6_api_exception_falls_back_to_template(monkeypatch):
    """AC6(a): 일반 예외 -> template_error."""
    def boom(**kw):
        raise RuntimeError("fail")
    state = _mock_client(monkeypatch, boom)
    text, source = guidance.generate_guidance_with_source("x")
    assert text == guidance.TEMPLATE
    assert source == "template_error"
    assert len(state["calls"]) == 1


def test_ac6_timeout_falls_back_and_request_timeout_is_10(monkeypatch):
    """AC6(b): create가 timeout=10 키워드로 호출된 뒤 APITimeoutError -> template_timeout."""
    def slow(**kw):
        raise anthropic.APITimeoutError(request=types.SimpleNamespace(method="POST", url="https://api.anthropic.com"))
    state = _mock_client(monkeypatch, slow)
    text, source = guidance.generate_guidance_with_source("x")
    assert len(state["calls"]) == 1
    assert state["calls"][0][1].get("timeout") == 10
    assert text == guidance.TEMPLATE
    assert source == "template_timeout"


def test_ac6_no_key_uses_template_without_client(monkeypatch):
    """AC6(c): 키 없음 -> 클라이언트 미생성, template_no_key."""
    state = _mock_client(monkeypatch, lambda **kw: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text, source = guidance.generate_guidance_with_source("x")
    assert text == guidance.TEMPLATE
    assert source == "template_no_key"
    assert state["created"] == 0 and state["calls"] == []


def test_ac6_success_uses_api_text(monkeypatch):
    """AC6(d): 정상 응답 -> 응답 문구, claude."""
    msg = types.SimpleNamespace(content=[types.SimpleNamespace(text="안내 초안")])
    state = _mock_client(monkeypatch, lambda **kw: msg)
    assert guidance.generate_guidance_with_source("x") == ("안내 초안", "claude")
    assert state["calls"][0][1].get("timeout") == 10


@pytest.mark.parametrize("val", ["", "   "])
def test_ac6_blank_key_is_no_key(monkeypatch, val):
    state = _mock_client(monkeypatch, lambda **kw: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", val)
    text, source = guidance.generate_guidance_with_source("x")
    assert text and source == guidance.SOURCE_NO_KEY
    assert state["created"] == 0
