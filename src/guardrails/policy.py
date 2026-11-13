"""[guardrails] 서비스 정책(예: 국내 임직원 전용) 판별. 1차 규칙보다 먼저 적용한다."""
import re

from ..shared.text import normalize


def match_policy(voc_text, policies):
    """정책에 해당하면 그 정책, 아니면 None.

    patterns(공백 무시 부분 문자열) 또는 regex(원문 검색)가 맞고, require_any가 있으면
    그중 하나(접속·사용·승인 등)도 본문에 있어야 한다. 그래서 해외 법인 관련 보안 신고나
    개선 제안처럼 사용 요청이 아닌 문의는 막지 않는다.
    """
    text = normalize(voc_text)
    for p in policies:
        hit = (any(normalize(t) and normalize(t) in text for t in p.get("patterns", []))
               or any(re.search(rx, voc_text or "") for rx in p.get("regex", [])))
        need = p.get("require_any") or []
        if hit and (not need or any(normalize(t) in text for t in need)):
            return p
    return None
