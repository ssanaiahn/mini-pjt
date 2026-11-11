"""입력 가드: VOC 본문의 개인정보를 가린 뒤 저장·LLM 전달에 사용한다."""
import re

PATTERNS = [
    ("주민등록번호", re.compile(r"\b\d{6}\s*-\s*[1-4]\d{6}\b"), "[주민번호]"),
    ("전화번호", re.compile(r"\b01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}\b"), "[전화번호]"),
    ("이메일", re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b"), "[이메일]"),
]


def mask_pii(text):
    """(가린 본문, 발견한 개인정보 종류 목록)."""
    found = []
    for label, pattern, repl in PATTERNS:
        text, n = pattern.subn(repl, text)
        if n:
            found.append(label)
    return text, found
