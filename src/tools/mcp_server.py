"""[tools] VOC 업무 도구 MCP 서버 (fastmcp, stdio). 모의 데이터만 다루며 모두 읽기 전용이다.

과거 VOC 의미 검색(search_similar_vocs)은 임베딩·Chroma가 stdio 서버 안에서 응답하지 않는 문제가
있어, 앱 프로세스의 로컬 도구로 둔다(src/judgement/agent.py).

실행: python -m src.tools.mcp_server (프로젝트 루트에서)
DB·메뉴 경로는 환경변수 VOC_DB_PATH, VOC_MENUS_PATH를 따른다(클라이언트가 그대로 전달).
"""
import sys
from pathlib import Path

if __package__ in (None, ""):  # python src/tools/mcp_server.py 로 직접 실행한 경우
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastmcp import FastMCP

from src.tools import tool_logic as tools

mcp = FastMCP("voc-tools")


@mcp.tool()
def list_menus() -> str:
    """처리 가능한 등록 메뉴명과 별칭 목록을 JSON으로 돌려준다.

    VOC가 어느 메뉴에 해당하는지 판단하기 전에 항상 먼저 호출한다.
    """
    return tools.list_menus()


@mcp.tool()
def get_menu_count(menu: str) -> str:
    """메뉴별 처리 가능 VOC 누적 건수를 돌려준다.

    Args:
        menu: 등록 메뉴명(list_menus의 name)
    """
    return tools.get_menu_count(menu)


@mcp.tool()
def lookup_account(user_id: str) -> str:
    """등록자 계정 정보(모의 DB)를 조회한다. 없으면 found=false.

    Args:
        user_id: 등록자 ID (예: u001)
    """
    return tools.lookup_account(user_id)


@mcp.tool()
def lookup_business_data(user_id: str, menu: str) -> str:
    """등록자의 메뉴별 업무 데이터(모의 DB)를 조회한다.

    Args:
        user_id: 등록자 ID
        menu: 등록 메뉴명
    """
    return tools.lookup_business_data(user_id, menu)


if __name__ == "__main__":
    mcp.run(show_banner=False, log_level="WARNING")
