"""입력 가드: VOC 본문의 개인정보를 가린 뒤 저장·LLM 전달에 사용한다."""
import re

# \b 대신 숫자 경계를 쓴다: 한글도 단어 문자라 "010-1234-5678로"처럼 조사가 붙으면 \b가 실패한다.
# 이메일은 영문·숫자만 매칭해 뒤에 붙은 조사("으로")를 지우지 않는다.
PATTERNS = [
    ("주민등록번호", re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)"), "[주민번호]"),
    ("전화번호", re.compile(r"(?<!\d)01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}(?!\d)"), "[전화번호]"),
    ("이메일", re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
                         r"\.[A-Za-z]{2,}"), "[이메일]"),
]


def mask_pii(text):
    """(가린 본문, 발견한 개인정보 종류 목록)."""
    found = []
    for label, pattern, repl in PATTERNS:
        text, n = pattern.subn(repl, text)
        if n:
            found.append(label)
    return text, found
