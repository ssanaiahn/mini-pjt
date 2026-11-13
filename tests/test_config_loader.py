import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.shared.config import load_menus  # noqa: E402


def _write(tmp_path, menus):
    p = tmp_path / "menus.json"
    p.write_text(json.dumps({"menus": menus}, ensure_ascii=False), encoding="utf-8")
    return p


def test_ac8_duplicate_alias_across_menus_is_error(tmp_path):
    p = _write(tmp_path, [{"name": "A메뉴", "aliases": ["공유 별칭"]},
                          {"name": "B메뉴", "aliases": ["공유별칭"]}])
    with pytest.raises(ValueError):
        load_menus(p)


def test_ac8_missing_file_is_error(tmp_path):
    with pytest.raises(OSError):
        load_menus(tmp_path / "none.json")


def test_ac8_valid_config_loads(tmp_path):
    p = _write(tmp_path, [{"name": "A", "aliases": ["x"]}, {"name": "B", "aliases": ["y"]}])
    assert len(load_menus(p)) == 2


def test_ac8_duplicate_after_normalization_name_vs_alias(tmp_path):
    p = _write(tmp_path, [{"name": "주문 조회", "aliases": []},
                          {"name": "다른메뉴", "aliases": ["주문조회"]}])
    with pytest.raises(ValueError):
        load_menus(p)


def test_ac8_duplicate_after_normalization_names(tmp_path):
    p = _write(tmp_path, [{"name": "주문 조회", "aliases": []},
                          {"name": "주문조회", "aliases": []}])
    with pytest.raises(ValueError):
        load_menus(p)


def test_ac8_same_menu_name_and_alias_matched_once_count_plus_one(tmp_path):
    from src.shared.db import connect, init_db
    from src.judgement.rules import match_menus
    from src.workflows.voc_graph import process_voc

    menus = [{"name": "주문 조회", "aliases": ["오더조회", "Order"]},
             {"name": "배송", "aliases": []}]
    text = "주문조회 오더 조회 ORDER 주문 조회가 안돼요"
    assert match_menus(text, menus) == ["주문 조회"]
    conn = connect(tmp_path / "t.db")
    init_db(conn, reset=True, menus=menus)
    r = process_voc(conn, text, "u001", menus=menus, use_api=False)
    assert r["matched_menus"] == ["주문 조회"]
    assert r["count_snapshot"] == {"주문 조회": 1}
    conn.close()


def test_ac8_longer_alias_wins_over_contained_short_menu():
    from src.judgement.rules import match_menus

    menus = [{"name": "주문내역", "aliases": []}, {"name": "주문", "aliases": []}]
    assert match_menus("주문내역 확인", menus) == ["주문내역"]
