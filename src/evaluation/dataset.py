"""평가 데이터 로딩·검증.

- 인-아웃 세트(test_queries.json): 평가 문의와 정답
- 과거 이력(seed_history.csv): 검색 대상이 될 메뉴명 판정 과거 VOC
형식이 어긋나면 ValueError(항목 id 또는 행 번호 포함)로 바로 알린다.
"""
import csv
import json
from pathlib import Path

from ..judgement.rules import match_menus
from ..shared.config import load_menus
from ..shared.llm import ROOT

DIR = ROOT / "evaluation"  # 평가 데이터·리포트 폴더(코드는 src/evaluation)
QUERIES_PATH = DIR / "test_queries.json"
SEED_PATH = DIR / "seed_history.csv"

CATEGORIES = ("paraphrase", "lookalike", "rule_conflict", "guardrail", "policy")
CHECKS = ("pii_masked", "no_unregistered_menu", "not_processable", "policy_message")
NO_RULE_CATEGORIES = ("paraphrase", "lookalike")  # 의미 판정 평가: 1차 규칙에 걸리면 안 됨


def _check_query(c, names, menus):
    cid = c["id"]

    def bad(msg):
        raise ValueError(f"{cid}: {msg}")

    if c["category"] not in CATEGORIES:
        bad(f"알 수 없는 category '{c['category']}'")
    unknown = [m for m in c["expected_menus"] if m not in names]
    if unknown:
        bad(f"등록되지 않은 메뉴 {unknown}")
    if bool(c["expected_processable"]) != bool(c["expected_menus"]):
        bad("expected_processable과 expected_menus가 맞지 않음")
    for chk in c["checks"]:
        if chk not in CHECKS:
            bad(f"알 수 없는 check '{chk}'")
    for v in c["pii_values"]:
        if v not in c["text"]:
            bad(f"pii_values '{v}'가 본문에 없음")
    hits = match_menus(c["text"], menus)
    if c["category"] in NO_RULE_CATEGORIES and hits:
        bad(f"메뉴명·별칭이 들어 있음 {hits}")
    if c["category"] == "rule_conflict" and not hits:
        bad("1차 규칙에 걸리는 별칭이 없음")


def load_queries(path=QUERIES_PATH, menus=None):
    menus = menus or load_menus()
    names = {m["name"] for m in menus}
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out, seen = [], set()
    for raw in items:
        c = {"registrant_id": "u001", "checks": [], "pii_values": [], "note": "", **raw}
        if c["id"] in seen:
            raise ValueError(f"{c['id']}: id 중복")
        seen.add(c["id"])
        _check_query(c, names, menus)
        out.append(c)
    return out


def load_seed(path=SEED_PATH, menus=None):
    menus = menus or load_menus()
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            want = [m for m in row["menus"].split("|") if m]
            got = match_menus(row["text"], menus)
            if set(want) != set(got):
                raise ValueError(f"과거 이력 {i}행: 규칙 판정 {got} ≠ 적은 메뉴 {want}")
            out.append({"text": row["text"], "registrant_id": row["registrant_id"], "menus": want})
    return out
