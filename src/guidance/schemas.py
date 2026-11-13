"""[guidance] 안내 문구 출력 스키마와 문구 출처 값."""
from pydantic import BaseModel, Field

SOURCE_CLAUDE = "claude"
SOURCE_NO_KEY = "template_no_key"
SOURCE_ERROR = "template_error"
SOURCE_TIMEOUT = "template_timeout"
GUIDANCE_SOURCES = (SOURCE_CLAUDE, SOURCE_NO_KEY, SOURCE_ERROR, SOURCE_TIMEOUT)


class GuidanceDraft(BaseModel):
    """안내 문구 초안(구조화 출력)."""
    message: str = Field(description="등록자에게 보낼 안내 문구 전체(5문장 이내)")
    reason: str = Field(description="처리할 수 없는 이유 한 문장")
    contact: str = Field(description="안내한 문의처(부서명 또는 '사내 헬프데스크')")
