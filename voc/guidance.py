"""처리 불가 VOC 안내 문구 초안: Claude API(키 있을 때) 또는 템플릿."""
import os

API_TIMEOUT = 10.0
MODEL = "claude-haiku-5-5"

TEMPLATE = (
    "안녕하세요. 문의해 주신 내용은 현재 등록된 처리 대상 메뉴에 해당하지 않아 "
    "바로 처리하기 어렵습니다. 담당 부서에 전달하여 확인 후 안내드리겠습니다. 감사합니다."
)


def template_guidance(voc_text):
    return TEMPLATE


def generate_guidance(voc_text, use_api=True):
    """API 키가 없거나 호출 실패/10초 초과 시 템플릿으로 대체한다."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not use_api or not key:
        return template_guidance(voc_text)
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key, timeout=API_TIMEOUT, max_retries=0)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content":
                       "다음 VOC는 등록 메뉴에 해당하지 않아 처리 불가입니다. "
                       f"등록자에게 보낼 정중한 한국어 안내 문구 초안을 써 주세요.\n\nVOC: {voc_text}"}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "text", None)).strip()
        return text or template_guidance(voc_text)
    except Exception:
        return template_guidance(voc_text)
