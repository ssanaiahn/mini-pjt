"""MCP 도구를 쓰는 Claude 에이전트 2개 (Bedrock, langchain create_agent).

- 판정 에이전트: 본문에 메뉴명이 없을 때 list_menus·search_similar_vocs로 메뉴를 판단하고
  구조화 출력(JudgeResult)으로 답한다.
- 조회 에이전트: 자주 들어오는 VOC일 때 lookup_account·lookup_business_data·get_menu_count로
  담당자용 요약을 쓴다.
어떤 오류·시간 초과도 None을 돌려주고, 호출한 쪽(그래프)이 규칙 기반으로 대체한다.
"""
import asyncio
import os
import sys

from pydantic import BaseModel, Field

from . import llm

AGENT_TIMEOUT = 60
JUDGE_TOOLS = ("list_menus", "get_menu_count")  # MCP 도구 (+ 로컬 search_similar_vocs)
LOOKUP_TOOLS = ("lookup_account", "lookup_business_data", "get_menu_count")

JUDGE_PROMPT = """너는 사내 시스템 VOC 접수 담당자를 돕는 판정 에이전트다.
VOC 본문에 등록 메뉴명이 그대로 들어 있지 않아, 의미로 판단해야 한다.

[절차]
1. list_menus로 등록 메뉴와 별칭을 확인한다.
2. search_similar_vocs로 의미가 비슷한 과거 VOC와 그 처리 메뉴를 확인한다.
3. VOC가 등록 메뉴 중 어디에 해당하는지 판단한다.

[판정 기준]
- VOC의 요청·문제가 등록 메뉴의 업무 범위에 분명히 속할 때만 processable=true.
- menus에는 list_menus의 name만 정확히 적는다(별칭 금지). 여러 개면 모두 적는다.
- 메뉴와 관계없는 잡담·타 업무 요청이면 processable=false, menus=[].
- 비슷한 과거 VOC가 있어도 내용이 실제로 같은 업무일 때만 근거로 쓴다.
- reason에는 판단 근거를 한국어 한두 문장으로 쓴다."""

LOOKUP_PROMPT = """너는 VOC 접수 담당자를 돕는 조회 에이전트다.
같은 메뉴의 VOC가 반복 접수되었다. 도구로 등록자 계정과 해당 메뉴의 업무 데이터, 누적 건수를
조회한 뒤, 담당자가 바로 조치할 수 있게 한국어로 3줄 이내 요약을 쓴다.
도구 결과에 있는 내용만 쓰고, 등록자 정보가 없으면 없다고 쓴다."""


class JudgeResult(BaseModel):
    """VOC 판정 결과."""
    processable: bool = Field(description="등록 메뉴로 처리 가능하면 true")
    menus: list[str] = Field(default_factory=list, description="해당 등록 메뉴명(name) 목록")
    reason: str = Field(description="판단 근거(한국어 한두 문장)")
    similar_voc_ids: list[int] = Field(default_factory=list,
                                       description="근거로 삼은 과거 VOC id 목록(없으면 빈 목록)")


def _local_search_tool():
    """과거 VOC 의미 검색 로컬 도구(앱 프로세스에서 실행)."""
    from langchain_core.tools import tool

    from . import tools

    @tool
    def search_similar_vocs(voc_text: str, k: int = 3) -> str:
        """과거에 메뉴명으로 처리된 VOC 중 의미가 가까운 건을 찾는다.

        결과의 menus는 그 과거 VOC가 처리된 메뉴이고, similarity는 0~1(높을수록 비슷함)이다.
        본문에 메뉴명이 없을 때 판정 근거로 사용한다.

        Args:
            voc_text: 판정할 VOC 본문
            k: 돌려받을 건수(기본 3)
        """
        return tools.search_similar_vocs(voc_text, k)

    return search_similar_vocs


def _mcp_client():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    return MultiServerMCPClient({
        "voc-tools": {
            "command": sys.executable,
            "args": ["-m", "voc.mcp_server"],
            "cwd": str(llm.ROOT),
            "env": dict(os.environ),  # DB 경로·AWS 자격 증명을 서버 프로세스에 전달
            "transport": "stdio",
        }
    })


async def get_tools(names):
    tools = await _mcp_client().get_tools()
    return [t for t in tools if t.name in names]


def _tool_calls(messages):
    """에이전트가 호출한 MCP 도구 이름(결과 제출용 JudgeResult 호출은 제외)."""
    return [c["name"] for m in messages for c in (getattr(m, "tool_calls", None) or [])
            if c["name"] != JudgeResult.__name__]


async def _judge(voc_text):
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy

    # ToolStrategy: 결과 형식도 '도구'로 받아야 MCP 도구를 먼저 호출한 뒤 결과를 낼 수 있다.
    # (자동 선택되는 ProviderStrategy는 Bedrock에서 첫 응답부터 결과 형식을 강제해 도구를 건너뜀)
    judge_tools = await get_tools(JUDGE_TOOLS) + [_local_search_tool()]  # MCP + 로컬 도구
    agent = create_agent(model=llm.chat_model(timeout=30), tools=judge_tools,
                         system_prompt=JUDGE_PROMPT, response_format=ToolStrategy(JudgeResult))
    out = await agent.ainvoke({"messages": [("user", (
        f"판정할 VOC 본문:\n{voc_text}\n\n"
        "list_menus와 search_similar_vocs 도구로 먼저 확인한 뒤 JudgeResult로 답하라."))]})
    r = out["structured_response"]
    return {"processable": r.processable, "menus": r.menus, "reason": r.reason,
            "similar_voc_ids": r.similar_voc_ids, "tool_calls": _tool_calls(out["messages"])}


async def _lookup(registrant_id, menus):
    from langchain.agents import create_agent

    agent = create_agent(model=llm.chat_model(timeout=30), tools=await get_tools(LOOKUP_TOOLS),
                         system_prompt=LOOKUP_PROMPT)
    out = await agent.ainvoke({"messages": [(
        "user", f"등록자 ID: {registrant_id}\n반복 접수 메뉴: {', '.join(menus)}")]})
    return {"summary": llm.text_of(out["messages"][-1]).strip(),
            "tool_calls": _tool_calls(out["messages"])}


def _run(coro):
    try:
        return asyncio.run(asyncio.wait_for(coro, AGENT_TIMEOUT))
    except Exception as e:  # 오류·시간 초과·도구 실패 모두 대체 경로로
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def judge_voc(voc_text):
    """{"processable", "menus", "reason", "similar_voc_ids", "tool_calls"} 또는 {"error"}."""
    return _run(_judge(voc_text))


def summarize_frequent(registrant_id, menus):
    """{"summary", "tool_calls"} 또는 {"error"}."""
    return _run(_lookup(registrant_id, menus))
