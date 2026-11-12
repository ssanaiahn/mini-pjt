"""안내 문구: Bedrock Claude(가짜 모델로 대체) 성공·오류·10초 초과·LLM 미사용."""
import socket
import types

import pytest
from botocore.exceptions import ReadTimeoutError

from voc import guidance, llm


@pytest.fixture(autouse=True)
def block_sockets(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


def _fake_model(monkeypatch, invoke):
    """llm.chat_model을 가짜로 교체. 생성 시 timeout과 invoke 호출을 기록."""
    state = {"created": [], "calls": []}

    def chat_model(timeout=30, max_tokens=800):
        state["created"].append(timeout)

        def rec(prompt):
            state["calls"].append(prompt)
            return invoke(prompt)
        return types.SimpleNamespace(invoke=rec)

    monkeypatch.setattr(llm, "chat_model", chat_model)
    monkeypatch.setenv("VOC_USE_LLM", "1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy")
    return state


def test_ac6_api_exception_falls_back_to_template(monkeypatch):
    def boom(prompt):
        raise RuntimeError("fail")
    state = _fake_model(monkeypatch, boom)
    assert guidance.generate_guidance_with_source("x") == (guidance.TEMPLATE, "template_error")
    assert len(state["calls"]) == 1


def test_ac6_timeout_falls_back_and_request_timeout_is_10(monkeypatch):
    def slow(prompt):
        raise ReadTimeoutError(endpoint_url="https://bedrock-runtime")
    state = _fake_model(monkeypatch, slow)
    assert guidance.generate_guidance_with_source("x") == (guidance.TEMPLATE, "template_timeout")
    assert state["created"] == [10]


def test_ac6_llm_disabled_uses_template_without_model(monkeypatch):
    state = _fake_model(monkeypatch, lambda p: None)
    monkeypatch.setenv("VOC_USE_LLM", "0")
    assert guidance.generate_guidance_with_source("x") == (guidance.TEMPLATE, "template_no_key")
    assert state["created"] == [] and state["calls"] == []


def test_ac6_no_aws_credentials_uses_template(monkeypatch):
    state = _fake_model(monkeypatch, lambda p: None)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    assert guidance.generate_guidance_with_source("x")[1] == "template_no_key"
    assert state["created"] == []


def test_ac6_success_uses_model_text_and_reason(monkeypatch):
    msg = types.SimpleNamespace(content=[{"type": "text", "text": "안내 초안"}])
    state = _fake_model(monkeypatch, lambda p: msg)
    out = guidance.generate_guidance_with_source("회의실 예약", reason="회의실은 등록 메뉴 아님")
    assert out == ("안내 초안", "claude")
    assert "회의실 예약" in state["calls"][0] and "회의실은 등록 메뉴 아님" in state["calls"][0]
    assert state["created"] == [10]


def test_guidance_prompt_forbids_promise_and_uses_hints(monkeypatch):
    msg = types.SimpleNamespace(content="안내")
    state = _fake_model(monkeypatch, lambda p: msg)
    guidance.generate_guidance_with_source("출입증 분실", hints=["출입카드 분실 (총무팀)"])
    prompt = state["calls"][0]
    assert "출입카드 분실 (총무팀)" in prompt and "약속" in prompt


def test_template_makes_no_promise():
    """가드레일 6: 처리·전달 약속 금지(규칙 모드 템플릿도 같음)."""
    assert "전달" not in guidance.TEMPLATE and "드리겠습니다" not in guidance.TEMPLATE


def test_department_hints_only_with_department():
    menus = [{"name": "a", "scope": {"excludes": ["x (총무팀)", "y"]}}, {"name": "b"}]
    assert guidance.department_hints(menus) == ["x (총무팀)"]


def test_ac6_empty_model_text_is_error(monkeypatch):
    _fake_model(monkeypatch, lambda p: types.SimpleNamespace(content="  "))
    assert guidance.generate_guidance_with_source("x")[1] == "template_error"
