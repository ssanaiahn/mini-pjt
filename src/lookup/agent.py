"""[lookup] 조회 에이전트: 반복 접수(누적 3 이상) 때 등록자 계정·업무 데이터·누적 건수를 조회해 요약.

조회 도구는 등록자 ID가 코드에서 고정된 래퍼로만 준다(LLM은 user_id를 고를 수 없음).
"""
from ..shared import llm
from ..shared.agent_runtime import run_agent, tool_call_names
from ..tools.mcp_client import get_tools
from .prompts import LOOKUP_PROMPT, lookup_message

LOOKUP_TOOLS = ("lookup_account", "lookup_business_data", "get_menu_count")


def _bound_lookup_tools(mcp_tools, registrant_id):
    """조회 MCP 도구를 등록자 ID가 고정된 도구로 감싼다(LLM은 user_id를 고를 수 없음).

    LLM이 "u001' --" 같은 ID를 u001로 '고쳐' 다른 사람을 조회하던 문제를 막는다.
    입력된 ID는 그대로(파라미터 바인딩) MCP 도구에 전달된다.
    """
    from langchain_core.tools import StructuredTool

    by = {t.name: t for t in mcp_tools}

    async def call(name, args):
        return llm.text_of(await by[name].ainvoke(args))

    async def lookup_account() -> str:
        """이번 VOC 등록자의 계정 정보(모의 DB). 없으면 found=false."""
        return await call("lookup_account", {"user_id": registrant_id})

    async def lookup_business_data(menu: str) -> str:
        """이번 VOC 등록자의 해당 메뉴 업무 데이터(모의 DB).

        Args:
            menu: 등록 메뉴명
        """
        return await call("lookup_business_data", {"user_id": registrant_id, "menu": menu})

    async def get_menu_count(menu: str) -> str:
        """메뉴별 처리 가능 VOC 누적 건수.

        Args:
            menu: 등록 메뉴명
        """
        return await call("get_menu_count", {"menu": menu})

    return [StructuredTool.from_function(coroutine=f, name=f.__name__)
            for f in (lookup_account, lookup_business_data, get_menu_count)]


async def _lookup(registrant_id, menus, history=None):
    from langchain.agents import create_agent

    tools = _bound_lookup_tools(await get_tools(LOOKUP_TOOLS), registrant_id)
    agent = create_agent(model=llm.chat_model(timeout=30), tools=tools,
                         system_prompt=LOOKUP_PROMPT)
    out = await agent.ainvoke({"messages": [("user", lookup_message(registrant_id, menus, history))]})
    return {"summary": llm.text_of(out["messages"][-1]).strip(),
            "tool_calls": tool_call_names(out["messages"])}


def summarize_frequent(registrant_id, menus, history=None):
    """{"summary", "tool_calls"} 또는 {"error"}. history: 유사 VOC 처리 이력(find_similar_history)."""
    return run_agent(_lookup(registrant_id, menus, history))
