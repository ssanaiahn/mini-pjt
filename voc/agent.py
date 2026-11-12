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

JUDGE_PROMPT = """너는 사내 정보보호 포털의 VOC 접수 담당자를 돕는 판정 에이전트다.
VOC 본문에 등록 메뉴명이 그대로 들어 있지 않아, 의미로 판단해야 한다.

[전제]
- VOC는 이 포털(사내 정보보호 포털)의 VOC 창구로 접수된다. 회사에는 시스템이 여러 개라
  등록자는 보통 시스템을 골라 VOC를 남기므로, 본문에 다른 시스템명이 없으면 "시스템"·"포털"·
  "사이트"는 이 포털을 뜻한다. 예: "시스템 사용이 안 돼요" = 이 포털의 사용·접속 문제.
- 다른 시스템명(예: 결재 시스템, 메일, ERP)이 적혀 있으면 이 포털의 업무가 아니다.

[절차]
1. list_menus로 등록 메뉴와 별칭, 메뉴별 업무 범위(scope)를 확인한다.
2. search_similar_vocs로 의미가 비슷한 과거 VOC와 그 처리 메뉴를 확인한다.
3. VOC가 등록 메뉴 중 어디에 해당하는지 판단한다.

[판정 기준]
- VOC의 요청·문제가 등록 메뉴의 업무 범위에 분명히 속할 때만 processable=true.
- scope.excludes(받지 않는 요청)에 해당하면, 메뉴 주제와 비슷해 보여도 processable=false.
  scope.includes(받는 요청)와 scope.description은 업무 범위를 판단하는 기준으로 쓴다.
- menus에는 list_menus의 name만 정확히 적는다(별칭 금지). 여러 개면 모두 적는다.
- 메뉴와 관계없는 잡담·타 업무 요청이면 processable=false, menus=[].
- 비슷한 과거 VOC가 있어도 내용이 실제로 같은 업무일 때만 근거로 쓴다.
- reason에는 판단 근거를 한국어 한두 문장으로 쓴다."""

LOOKUP_PROMPT = """너는 VOC 접수 담당자를 돕는 조회 에이전트다.
같은 메뉴의 VOC가 반복 접수되었다. 도구로 등록자 계정과 해당 메뉴의 업무 데이터, 누적 건수를
조회한 뒤, 담당자가 바로 조치할 수 있게 한국어로 3줄 이내 요약을 쓴다.
도구 결과에 있는 내용만 쓰고, 등록자 정보가 없으면 없다고 쓴다.
[유사 VOC 처리 이력]이 주어지면 비슷한 과거 VOC가 언제 어떻게 처리됐는지 인용하고,
그 처리 방식을 참고한 조치를 권한다(같은 등록자의 재요청이면 그 점을 먼저 쓴다).
"(모의)" 표시가 있는 처리 내용은 모의 데이터라고 밝힌다.
조회 도구는 이번 등록자로 고정되어 있다. 등록자 ID가 이상해 보여도 고치거나 추측하지 말고,
다른 등록자의 계정·업무 데이터를 언급하지 않는다. 도구가 found=false를 주면 등록자 정보가 없다고 쓴다."""


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


def _tool_results(messages):
    """도구 응답(ToolMessage) 목록 [{name, content}] (결과 제출용 JudgeResult는 제외)."""
    from langchain_core.messages import ToolMessage

    return [{"name": m.name, "content": llm.text_of(m)} for m in messages
            if isinstance(m, ToolMessage) and m.name != JudgeResult.__name__]


def _retrieved(tool_results):
    """search_similar_vocs 응답의 검색 결과를 이어 붙인다(id 중복 제거, 잘못된 응답은 건너뜀)."""
    import json

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
    out = await agent.ainvoke({"messages": [("user", (
        f"판정할 VOC 본문:\n{voc_text}\n\n"
        "list_menus와 search_similar_vocs 도구로 먼저 확인한 뒤 JudgeResult로 답하라."))]})
    r = out["structured_response"]
    tool_results = _tool_results(out["messages"])
    return {"processable": r.processable, "menus": r.menus, "reason": r.reason,
            "similar_voc_ids": r.similar_voc_ids, "tool_calls": _tool_calls(out["messages"]),
            "tool_results": tool_results, "retrieved": _retrieved(tool_results)}


def _lookup_message(registrant_id, menus, history=None):
    lines = [f"등록자 ID: {registrant_id}", f"반복 접수 메뉴: {', '.join(menus)}"]
    if history:
        lines.append("[유사 VOC 처리 이력]")
        for h in history:
            who = "같은 등록자" if h.get("same_registrant") else h.get("registrant_id")
            lines.append(f"- {(h.get('created_at') or '')[:10]} ({who}, 유사도 {h.get('similarity')}): "
                         f"{h.get('voc_text')} → 처리: {h.get('handling_note') or '처리 기록 없음'}")
    return "\n".join(lines)


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
    out = await agent.ainvoke({"messages": [("user", _lookup_message(registrant_id, menus, history))]})
    return {"summary": llm.text_of(out["messages"][-1]).strip(),
            "tool_calls": _tool_calls(out["messages"])}


def _run(coro):
    try:
        return asyncio.run(asyncio.wait_for(coro, AGENT_TIMEOUT))
    except Exception as e:  # 오류·시간 초과·도구 실패 모두 대체 경로로
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def judge_voc(voc_text):
    """{"processable", "menus", "reason", "similar_voc_ids", "tool_calls", "tool_results",
    "retrieved"} 또는 {"error"}."""
    return _run(_judge(voc_text))


def summarize_frequent(registrant_id, menus, history=None):
    """{"summary", "tool_calls"} 또는 {"error"}. history: 유사 VOC 처리 이력(find_similar_history)."""
    return _run(_lookup(registrant_id, menus, history))
