"""처리 불가 VOC 안내 문구 초안: Bedrock Claude(사용 가능 시) 또는 템플릿."""
from . import llm

SOURCE_CLAUDE = "claude"
SOURCE_NO_KEY = "template_no_key"
SOURCE_ERROR = "template_error"
SOURCE_TIMEOUT = "template_timeout"
GUIDANCE_SOURCES = (SOURCE_CLAUDE, SOURCE_NO_KEY, SOURCE_ERROR, SOURCE_TIMEOUT)

API_TIMEOUT = 10

TEMPLATE = (
    "안녕하세요. 문의해 주신 내용은 현재 등록된 처리 대상 메뉴에 해당하지 않아 "
    "이 창구에서는 처리하기 어렵습니다. 번거로우시겠지만 사내 헬프데스크나 조직도에서 "
    "담당 부서를 확인해 문의해 주시기 바랍니다. 감사합니다."
)

PROMPT = (
    "다음 VOC는 사내 시스템의 등록 메뉴에 해당하지 않아 처리 불가로 판정되었습니다. "
    "등록자에게 보낼 정중한 한국어 안내 문구 초안을 5문장 이내로 써 주세요. "
    "처리할 수 없는 이유와 적절한 문의처를 찾도록 돕는 내용을 담고, 문구만 출력하세요.\n"
    "- 이 창구에서 처리하거나 전달하겠다는 약속(예: '처리해 드리겠습니다', '전달하겠습니다')은 쓰지 마세요.\n"
    "- 아래 [담당 부서 참고]에 이 VOC와 맞는 항목이 있으면 그 부서를 문의처로 안내하세요. "
    "없으면 부서를 지어내지 말고 사내 헬프데스크나 조직도에서 담당 부서를 확인하도록 안내하세요.\n"
    "- 전화번호·이메일 같은 연락처는 지어내지 마세요.\n\n"
    "VOC: {voc}{reason}{hints}"
)


def department_hints(menus):
    """업무 범위의 '받지 않는 요청' 중 담당 부서(괄호)가 적힌 항목."""
    return [x for m in menus for x in (m.get("scope") or {}).get("excludes", [])
            if "(" in x and x.rstrip().endswith(")")]


def template_guidance(voc_text):
    return TEMPLATE


def _is_timeout(e):
    names = {c.__name__ for c in type(e).__mro__}
    return bool(names & {"ReadTimeoutError", "ConnectTimeoutError", "TimeoutError",
                         "ConnectTimeout", "ReadTimeout"})


def generate_guidance_with_source(voc_text, use_api=True, reason=None, hints=None):
    """(문구, guidance_source). LLM 미사용·오류·10초 초과 시 템플릿으로 대체.

    hints: 담당 부서 참고 항목(department_hints) — 문의처 안내에 쓴다.
    """
    if not use_api or not llm.llm_enabled():
        return template_guidance(voc_text), SOURCE_NO_KEY
    try:
        model = llm.chat_model(timeout=API_TIMEOUT, max_tokens=400)
        msg = model.invoke(PROMPT.format(
            voc=voc_text, reason=f"\n판정 근거: {reason}" if reason else "",
            hints=("\n[담당 부서 참고]\n" + "\n".join(f"- {h}" for h in hints)) if hints else ""))
        text = llm.text_of(msg).strip()
        if text:
            return text, SOURCE_CLAUDE
        return template_guidance(voc_text), SOURCE_ERROR
    except Exception as e:
        return template_guidance(voc_text), SOURCE_TIMEOUT if _is_timeout(e) else SOURCE_ERROR


def generate_guidance(voc_text, use_api=True):
    return generate_guidance_with_source(voc_text, use_api)[0]
