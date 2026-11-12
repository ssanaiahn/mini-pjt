"""조회 에이전트가 등록자 ID를 바꿔 다른 사람을 조회하지 못하게(ID는 코드가 고정).

배경: 등록자 ID "u001' --"로 입력했더니 LLM이 이를 u001로 고쳐 조회해
다른 사용자(u001)의 계정 정보가 요약에 노출됐다(2026-11-12 UI 테스트).
"""
import asyncio

from voc import agent


class FakeMcpTool:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    async def ainvoke(self, args):
        self.calls.append((self.name, dict(args)))
        return [{"type": "text", "text": f'{{"tool": "{self.name}"}}'}]


def bound(registrant_id):
    calls = []
    tools = agent._bound_lookup_tools(
        [FakeMcpTool(n, calls) for n in ("lookup_account", "lookup_business_data", "get_menu_count")],
        registrant_id)
    return {t.name: t for t in tools}, calls


def test_bound_tools_have_no_user_id_parameter():
    tools, _ = bound("u001' --")
    assert set(tools) == {"lookup_account", "lookup_business_data", "get_menu_count"}
    for t in tools.values():
        assert "user_id" not in t.args


def test_bound_tools_always_use_entered_registrant_id():
    tools, calls = bound("u001' --")
    out = asyncio.run(tools["lookup_account"].ainvoke({}))
    asyncio.run(tools["lookup_business_data"].ainvoke({"menu": "비밀유지계약"}))
    asyncio.run(tools["get_menu_count"].ainvoke({"menu": "비밀유지계약"}))
    assert calls == [("lookup_account", {"user_id": "u001' --"}),
                     ("lookup_business_data", {"user_id": "u001' --", "menu": "비밀유지계약"}),
                     ("get_menu_count", {"menu": "비밀유지계약"})]
    assert out == '{"tool": "lookup_account"}'  # 블록 리스트도 문자열로


def test_lookup_prompt_says_id_is_fixed():
    assert "다른 등록자" in agent.LOOKUP_PROMPT
