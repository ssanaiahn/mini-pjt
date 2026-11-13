"""평가 데이터(인-아웃 세트·과거 이력) 로딩과 검증."""
import json

import pytest

from src.evaluation.dataset import load_queries, load_seed

MENUS = [
    {"name": "보안 신고", "aliases": []},
    {"name": "사용자 관리", "aliases": ["접속"]},
]


def q(**kw):
    base = {"id": "P01", "category": "paraphrase", "text": "이상한 메일을 받았어요",
            "expected_processable": True, "expected_menus": ["보안 신고"]}
    return {**base, **kw}


def write(tmp_path, items):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return p


def load(tmp_path, items):
    return load_queries(write(tmp_path, items), menus=MENUS)


def test_load_queries_ok(tmp_path):
    items = [q(),
             q(id="L01", category="lookalike", text="출입카드를 잃어버렸어요",
               expected_processable=False, expected_menus=[]),
             q(id="C01", category="rule_conflict", text="해외에서 접속하게 해주세요",
               expected_processable=False, expected_menus=[]),
             q(id="G01", category="guardrail", text="010-1111-2222로 연락 주세요",
               expected_processable=False, expected_menus=[], checks=["pii_masked"],
               pii_values=["010-1111-2222"])]
    out = load(tmp_path, items)
    assert [c["id"] for c in out] == ["P01", "L01", "C01", "G01"]
    assert out[0]["checks"] == [] and out[0]["pii_values"] == []
    assert out[0]["registrant_id"] == "u001" and out[0]["note"] == ""


def test_policy_category_and_check(tmp_path):
    out = load(tmp_path, [q(id="X01", category="policy", text="현지 법인 소속입니다",
                            expected_processable=False, expected_menus=[],
                            checks=["policy_message"])])
    assert out[0]["category"] == "policy" and out[0]["checks"] == ["policy_message"]


@pytest.mark.parametrize("items, msg", [
    ([q(), q()], "P01"),
    ([q(category="other")], "category"),
    ([q(expected_menus=["없는 메뉴"])], "없는 메뉴"),
    ([q(checks=["nope"])], "nope"),
    ([q(text="보안 신고 문의")], "P01"),
    ([q(id="C01", category="rule_conflict", text="메일이 이상해요")], "C01"),
    ([q(expected_menus=[])], "P01"),
    ([q(expected_processable=False)], "P01"),
    ([q(pii_values=["010-0000-0000"])], "P01"),
])
def test_reject_invalid(tmp_path, items, msg):
    with pytest.raises(ValueError, match=msg):
        load(tmp_path, items)


def write_seed(tmp_path, rows):
    p = tmp_path / "seed.csv"
    p.write_text("text,registrant_id,menus\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_load_seed_ok(tmp_path):
    out = load_seed(write_seed(tmp_path, ["보안 신고 접수했어요,u001,보안 신고",
                                          "접속이 안 되고 보안 신고도 할게요,u002,사용자 관리|보안 신고"]),
                    menus=MENUS)
    assert out[1] == {"text": "접속이 안 되고 보안 신고도 할게요", "registrant_id": "u002",
                      "menus": ["사용자 관리", "보안 신고"]}


def test_seed_menus_must_match_rule(tmp_path):
    with pytest.raises(ValueError, match="2"):
        load_seed(write_seed(tmp_path, ["보안 신고 접수했어요,u001,보안 신고",
                                        "메일이 이상해요,u001,보안 신고"]), menus=MENUS)
