"""[shared] 텍스트 유틸: 정규화와 글자 2개 묶음(bigram) 유사도."""


def normalize(text):
    """공백을 모두 제거하고 영문을 소문자로 바꾼다."""
    return "".join((text or "").split()).lower()


def _bigrams(text):
    t = normalize(text)
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} - {""}


def similarity(a, b):
    """공백 제거 후 글자 2개 묶음(bigram) 집합의 자카드 유사도(0~1)."""
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0
