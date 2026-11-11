"""AWS Bedrock(Claude·Titan 임베딩) 연결 설정.

- 프로젝트 루트의 .env를 읽는다(이미 설정된 환경변수는 덮어쓰지 않음).
- LLM 사용 조건: VOC_USE_LLM이 0/false가 아니고, AWS 자격 증명(AWS_ACCESS_KEY_ID 또는 AWS_PROFILE)이 있음.
  조건이 안 되면 앱은 규칙 기반(메뉴명 → 글자 유사도)과 템플릿 문구로만 동작한다.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHAT_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # VOC_BEDROCK_MODEL로 변경 가능
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
DEFAULT_REGION = "us-east-1"


def load_env(path=None):
    """간단한 .env 로더: KEY=VALUE 줄만 읽고, 이미 있는 환경변수는 유지."""
    p = Path(path or ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def llm_enabled():
    if (os.environ.get("VOC_USE_LLM") or "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return bool((os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE") or "").strip())


def region():
    return os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or DEFAULT_REGION


def chat_model(timeout=30, max_tokens=800):
    """Bedrock Claude. timeout: 응답 대기 초(재시도 없음)."""
    from botocore.config import Config
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=os.environ.get("VOC_BEDROCK_MODEL") or CHAT_MODEL,
        region_name=region(),
        temperature=0,
        max_tokens=max_tokens,
        config=Config(connect_timeout=5, read_timeout=timeout,
                      retries={"max_attempts": 1, "mode": "standard"}),
    )


def embeddings():
    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(model_id=EMBED_MODEL, region_name=region())


def text_of(message):
    """ChatBedrockConverse 응답 content(문자열 또는 블록 리스트)에서 텍스트만 모은다."""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")
