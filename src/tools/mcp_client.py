"""[tools] MCP 클라이언트: src/tools/mcp_server.py를 stdio 하위 프로세스로 띄워 도구를 가져온다."""
import os
import sys

from ..shared import llm


def _mcp_client():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    return MultiServerMCPClient({
        "voc-tools": {
            "command": sys.executable,
            "args": ["-m", "src.tools.mcp_server"],
            "cwd": str(llm.ROOT),
            "env": dict(os.environ),  # DB 경로·AWS 자격 증명을 서버 프로세스에 전달
            "transport": "stdio",
        }
    })


async def get_tools(names):
    tools = await _mcp_client().get_tools()
    return [t for t in tools if t.name in names]
