"""모든 테스트는 기본적으로 LLM(Bedrock)을 끄고 규칙 경로로 실행한다.

.env에 AWS 자격 증명이 있어도 VOC_USE_LLM=0이 우선한다(load_env는 기존 값을 덮어쓰지 않음).
LLM 경로 테스트는 VOC_USE_LLM=1로 바꾸고 에이전트·모델을 가짜로 바꿔 끼운다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("VOC_USE_LLM", "0")
    monkeypatch.setenv("VOC_CHROMA_PATH", str(tmp_path / "chroma"))
