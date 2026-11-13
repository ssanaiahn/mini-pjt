"""[judgement] 판정 에이전트(Bedrock Claude, langchain create_agent + ToolStrategy).

본문에 메뉴명이 없거나(2차) 재확인 키워드가 있을 때, MCP 도구 list_menus·get_menu_count와
로컬 도구 search_similar_vocs로 확인한 뒤 구조화 출력(JudgeResult)으로 판정한다.
어떤 오류·시간 초과도 {"error"}로 돌려주고, 호출한 쪽(워크플로)이 대체 경로로 간다.
"""
import json

from ..shared import llm
from ..shared.agent_runtime import run_agent, tool_call_names
from ..tools.mcp_client import get_tools
from .prompts import JUDGE_PROMPT, JUDGE_USER_TEMPLATE, SEARCH_TOOL_DESCRIPTION
from .schemas import JudgeResult

JUDGE_TOOLS = ("list_menus", "get_menu_count")  # MCP 도구 (+ 로컬 search_similar_vocs)


def _local_search_tool():
    """과거 VOC 하이브리드 검색 로컬 도구(앱 프로세스에서 실행; MCP stdio 안에서는 임베딩이 응답하지 않음)."""
    from langchain_core.tools import StructuredTool

    from ..tools import tool_logic

    def search_similar_vocs(voc_text: str, k: int = 3) -> str:
        return tool_logic.search_similar_vocs(voc_text, k)

    return StructuredTool.from_function(search_similar_vocs, name="search_similar_vocs",
                                        description=SEARCH_TOOL_DESCRIPTION)


def _tool_results(messages):
    """도구 응답(ToolMessage) 목록 [{name, content}] (결과 제출용 JudgeResult는 제외)."""
    from langchain_core.messages import ToolMessage

    return [{"name": m.name, "content": llm.text_of(m)} for m in messages
            if isinstance(m, ToolMessage) and m.name != JudgeResult.__name__]


def _retrieved(tool_results):
    """search_similar_vocs 응답의 검색 결과를 이어 붙인다(id 중복 제거, 잘못된 응답은 건너뜀)."""
    out, seen = [], set()
    for t in tool_results:
        if t["name"] != "search_similar_vocs":
            continue
        try:
            results = json.loads(t["content"]).get("results", [])
        except (ValueError, AttributeError):
            continue
        for r in results:
            if r.get("id") not in seen:
                seen.add(r.get("id"))
                out.append({k: r.get(k) for k in ("id", "voc_text", "menus", "similarity")})
    return out


async def _judge(voc_text):
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy

    # ToolStrategy: 결과 형식도 '도구'로 받아야 MCP 도구를 먼저 호출한 뒤 결과를 낼 수 있다.
    # (자동 선택되는 ProviderStrategy는 Bedrock에서 첫 응답부터 결과 형식을 강제해 도구를 건너뜀)
    judge_tools = await get_tools(JUDGE_TOOLS) + [_local_search_tool()]  # MCP + 로컬 도구
    agent = create_agent(model=llm.chat_model(timeout=30), tools=judge_tools,
                         system_prompt=JUDGE_PROMPT, response_format=ToolStrategy(JudgeResult))
    out = await agent.ainvoke({"messages": [("user", JUDGE_USER_TEMPLATE.format(voc_text=voc_text))]})
    r = out["structured_response"]
    tool_results = _tool_results(out["messages"])
    return {"processable": r.processable, "menus": r.menus, "reason": r.reason,
            "similar_voc_ids": r.similar_voc_ids,
            "tool_calls": tool_call_names(out["messages"], exclude=(JudgeResult.__name__,)),
            "tool_results": tool_results, "retrieved": _retrieved(tool_results)}


def judge_voc(voc_text):
    """{"processable", "menus", "reason", "similar_voc_ids", "tool_calls", "tool_results",
    "retrieved"} 또는 {"error"}."""
    return run_agent(_judge(voc_text))
