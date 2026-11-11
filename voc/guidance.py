"""처리 불가 VOC 안내 문구 초안: Claude API(키 있을 때) 또는 템플릿."""
import os

import anthropic

SOURCE_CLAUDE = "claude"
SOURCE_NO_KEY = "template_no_key"
SOURCE_ERROR = "template_error"
SOURCE_TIMEOUT = "template_timeout"
GUIDANCE_SOURCES = (SOURCE_CLAUDE, SOURCE_NO_KEY, SOURCE_ERROR, SOURCE_TIMEOUT)

API_TIMEOUT = 10
MODEL = "claude-haiku-5-5"

TEMPLATE = (
    "안녕하세요. 문의해 주신 내용은 현재 등록된 처리 대상 메뉴에 해당하지 않아 "
    "바로 처리하기 어렵습니다. 담당 부서에 전달하여 확인 후 안내드리겠습니다. 감사합니다."
)


def template_guidance(voc_text):
    return TEMPLATE


def generate_guidance_with_source(voc_text, use_api=True):
    """(문구, guidance_source). 키 없음/오류/10초 초과 시 템플릿으로 대체."""
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not use_api or not key:
        return template_guidance(voc_text), SOURCE_NO_KEY
    try:
        client = anthropic.Anthropic(api_key=key, timeout=API_TIMEOUT, max_retries=0)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=300,
            timeout=API_TIMEOUT,
            messages=[{"role": "user", "content":
                       "다음 VOC는 등록 메뉴에 해당하지 않아 처리 불가입니다. "
                       f"등록자에게 보낼 정중한 한국어 안내 문구 초안을 써 주세요.\n\nVOC: {voc_text}"}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "text", None)).strip()
        if text:
            return text, SOURCE_CLAUDE
        return template_guidance(voc_text), SOURCE_ERROR
    except anthropic.APITimeoutError:
        return template_guidance(voc_text), SOURCE_TIMEOUT
    except Exception:
        return template_guidance(voc_text), SOURCE_ERROR


def generate_guidance(voc_text, use_api=True):
    return generate_guidance_with_source(voc_text, use_api)[0]
