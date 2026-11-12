"""MCP 서버 도구: 함수 직접 호출 + 실제 stdio MCP 연결(LLM 없이)."""
import asyncio
import json

import pytest

from voc import agent, tools
from voc.db import connect, init_db, load_menus
from voc.service import process_voc


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    monkeypatch.setenv("VOC_DB_PATH", str(path))
    c = connect()
    init_db(c, reset=True)
    name = load_menus()[0]["name"]
    process_voc(c, f"{name} 메일이 안 와요", "u001")
    process_voc(c, "점심 메뉴 추천", "u001")
    c.close()
    return name


def test_list_menus_includes_scope(db):
    by = {m["name"]: m for m in json.loads(tools.list_menus())}
    sc = by["정보보호 규정"]["scope"]
    assert "사외 메일 발신 프로세스" in sc["excludes"] and sc["description"]
    assert "받지 않는 요청" in agent.JUDGE_PROMPT and "scope" in agent.JUDGE_PROMPT


def test_tool_functions(db):
    assert db in [m["name"] for m in json.loads(tools.list_menus())]
    assert json.loads(tools.get_menu_count(db)) == {"menu": db, "count": 1}
    acc = json.loads(tools.lookup_account("u001"))
    assert acc["found"] and acc["account"]["user_id"] == "u001"
    assert json.loads(tools.lookup_account("nobody")) == {"found": False, "account": None}
    rows = json.loads(tools.lookup_business_data("u001", db))
    assert rows and rows[0]["menu"] == db


def test_search_similar_bigram_when_llm_off(db):
    out = json.loads(tools.search_similar_vocs(f"{db} 메일이 안 와요"))
    assert out["method"] == "bigram"
    assert out["results"][0]["similarity"] == 1.0 and out["results"][0]["menus"] == [db]
    assert all("점심" not in r["voc_text"] for r in out["results"])  # 처리 불가 건 제외


def test_mcp_server_over_stdio(db):
    async def go():
        ts = await agent.get_tools(agent.JUDGE_TOOLS + agent.LOOKUP_TOOLS)
        names = {t.name for t in ts}
        by = {t.name: t for t in ts}
        menus = await by["list_menus"].ainvoke({})
        count = await by["get_menu_count"].ainvoke({"menu": db})
        return names, menus, count

    names, menus, count = asyncio.run(go())
    assert names == {"list_menus", "get_menu_count", "lookup_account", "lookup_business_data"}
    text = lambda v: v if isinstance(v, str) else "".join(  # noqa: E731
        b.get("text", "") if isinstance(b, dict) else str(b) for b in v)
    assert db in text(menus)
    assert json.loads(text(count))["count"] == 1


def test_local_search_tool(db):
    t = agent._local_search_tool()
    out = json.loads(t.invoke({"voc_text": f"{db} 메일이 안 와요"}))
    assert t.name == "search_similar_vocs" and out["results"][0]["menus"] == [db]
