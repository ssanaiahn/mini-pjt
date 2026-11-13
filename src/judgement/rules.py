"""[judgement] 1차 규칙 판정: 메뉴명·별칭 매칭과 재확인 키워드."""
import re

from ..shared.config import validate_menus
from ..shared.text import normalize


def match_menus(voc_text, menus):
    """정규화한 본문에서 긴 후보부터 겹치지 않게 매칭. 본문 등장 순서로 메뉴 반환."""
    validate_menus(menus)
    text = normalize(voc_text)
    terms = sorted(
        ((normalize(t), m["name"]) for m in menus for t in [m["name"], *m.get("aliases", [])]),
        key=lambda x: -len(x[0]))
    covered = [False] * len(text)
    first_pos = {}
    for term, menu in terms:
        if not term:
            continue
        start = text.find(term)
        while start != -1:
            end = start + len(term)
            if not any(covered[start:end]):
                covered[start:end] = [True] * len(term)
                first_pos[menu] = min(first_pos.get(menu, start), start)
                start = text.find(term, end)
            else:
                start = text.find(term, start + 1)
    return sorted(first_pos, key=first_pos.get)


def needs_recheck(voc_text, menus, matched):
    """1차 규칙으로 매칭됐지만 재확인 키워드(recheck_terms)가 있어 에이전트가 다시 판단할 메뉴.

    예: '접속'(사용자 관리 별칭)이 있어도 'AD'·'비밀번호'가 있으면 통합인증 문의일 수 있다.
    영문 키워드는 단어 단위(대소문자 무시)로, 한글 키워드는 공백 무시 부분 문자열로 찾는다.
    """
    text = normalize(voc_text)
    out = []
    for m in menus:
        if m["name"] not in matched:
            continue
        for t in m.get("recheck_terms", []):
            if t.isascii():
                hit = re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", voc_text or "", re.I)
            else:
                hit = normalize(t) in text
            if hit:
                out.append(m["name"])
                break
    return out
