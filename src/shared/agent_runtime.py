"""[shared] 에이전트 실행 공통: 시간 제한·오류 흡수, 호출한 도구 이름 수집."""
import asyncio

AGENT_TIMEOUT = 60


def run_agent(coro):
    """비동기 에이전트 실행. 오류·시간 초과·도구 실패는 {"error"}로 돌려 호출한 쪽이 대체 경로로 간다."""
    try:
        return asyncio.run(asyncio.wait_for(coro, AGENT_TIMEOUT))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def tool_call_names(messages, exclude=()):
    """에이전트가 호출한 도구 이름(exclude: 결과 제출용 구조화 출력 도구 등)."""
    return [c["name"] for m in messages for c in (getattr(m, "tool_calls", None) or [])
            if c["name"] not in exclude]
