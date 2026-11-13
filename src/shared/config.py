"""[shared] 메뉴·정책 설정(config/menus.json) 로딩과 검증."""
import json
import os

from .llm import ROOT
from .text import normalize

MENUS_PATH = ROOT / "config" / "menus.json"


def _path(path):
    return path or os.environ.get("VOC_MENUS_PATH") or MENUS_PATH


def load_menus(path=None):
    with open(_path(path), encoding="utf-8") as f:
        menus = json.load(f)["menus"]
    if not isinstance(menus, list):
        raise ValueError("menus 설정 형식이 올바르지 않습니다")
    validate_menus(menus)
    return menus


def load_policies(path=None):
    """서비스 정책 목록 [{id, description, patterns, regex, require_any, message}]. 없으면 빈 목록."""
    with open(_path(path), encoding="utf-8") as f:
        return json.load(f).get("policies", [])


def validate_menus(menus):
    """같은 메뉴명/별칭이 서로 다른 두 메뉴에 있으면 ValueError."""
    owner = {}
    for m in menus:
        for term in [m["name"], *m.get("aliases", [])]:
            key = normalize(term)
            if owner.setdefault(key, m["name"]) != m["name"]:
                raise ValueError(
                    f"중복 등록된 메뉴명/별칭 '{term}': {owner[key]} / {m['name']}")
