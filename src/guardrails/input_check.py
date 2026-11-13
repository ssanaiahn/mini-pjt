"""[guardrails] 입력 검증: 빈/공백 입력은 경고만 하고 저장하지 않는다."""


def validate_input(voc_text, registrant_id):
    warnings = []
    if not (voc_text or "").strip():
        warnings.append("VOC 본문을 입력하세요.")
    if not (registrant_id or "").strip():
        warnings.append("등록자 ID를 입력하세요.")
    return {"is_valid": not warnings, "warnings": warnings}
