"""[guidance] 처리 불가 VOC 안내 문구 초안: Bedrock Claude LCEL 체인(구조화 출력) 또는 템플릿."""
from ..shared import llm
from .prompts import SYSTEM_PROMPT, TEMPLATE, USER_PROMPT
from .schemas import (SOURCE_CLAUDE, SOURCE_ERROR, SOURCE_NO_KEY, SOURCE_TIMEOUT,
                      GuidanceDraft)

API_TIMEOUT = 10


def guidance_chain(model):
    """LCEL 체인: 프롬프트 템플릿 | 모델.with_structured_output(GuidanceDraft)."""
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("user", USER_PROMPT)])
    return prompt | model.with_structured_output(GuidanceDraft)


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
        model = llm.chat_model(timeout=API_TIMEOUT, max_tokens=600)
        draft = guidance_chain(model).invoke({
            "voc": voc_text, "reason": f"\n판정 근거: {reason}" if reason else "",
            "hints": ("\n[담당 부서 참고]\n" + "\n".join(f"- {h}" for h in hints)) if hints else ""})
        text = (draft.message or "").strip()
        if text:
            return text, SOURCE_CLAUDE
        return template_guidance(voc_text), SOURCE_ERROR
    except Exception as e:
        return template_guidance(voc_text), SOURCE_TIMEOUT if _is_timeout(e) else SOURCE_ERROR


def generate_guidance(voc_text, use_api=True):
    return generate_guidance_with_source(voc_text, use_api)[0]
