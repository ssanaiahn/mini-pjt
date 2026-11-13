"""[workflows] VOC 판정 그래프 상태 스키마."""
from typing import Any, Optional, TypedDict


class VocState(TypedDict, total=False):
    voc_text: str
    registrant_id: str
    input_validation: dict
    pii_found: list
    matched: list
    match_source: Optional[str]
    similar: Optional[dict]
    judge: Optional[dict]
    agent_error: Optional[str]
    recheck: list
    policy: Optional[dict]
    guidance: Optional[str]
    guidance_source: Optional[str]
    voc_id: int
    created_at: str
    snapshot: dict
    frequent: list
    account: Any
    business: list
    lookup_summary: Optional[dict]
    similar_history: list
    steps: list
