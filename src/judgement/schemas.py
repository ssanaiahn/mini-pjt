"""[judgement] 판정 에이전트 입출력 스키마."""
from pydantic import BaseModel, Field


class JudgeResult(BaseModel):
    """VOC 판정 결과(구조화 출력)."""
    processable: bool = Field(description="등록 메뉴로 처리 가능하면 true")
    menus: list[str] = Field(default_factory=list, description="해당 등록 메뉴명(name) 목록")
    reason: str = Field(description="판단 근거(한국어 한두 문장)")
    similar_voc_ids: list[int] = Field(default_factory=list,
                                       description="근거로 삼은 과거 VOC id 목록(없으면 빈 목록)")
