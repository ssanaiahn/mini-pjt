"""판정 에이전트가 도구 응답(메뉴 목록·검색 결과)을 결과에 담는지(네트워크 없음)."""
from langchain_core.messages import AIMessage, ToolMessage

from src.judgement import agent as judge_agent
from src.lookup import agent as lookup_agent

SEARCH = ('{"method":"embedding","results":[{"id":3,"voc_text":"보안 신고 접수",'
          '"menus":["보안 신고"],"similarity":0.71}]}')


def msgs():
    return [
        AIMessage(content="", tool_calls=[{"name": "list_menus", "args": {}, "id": "1"}]),
        ToolMessage(content='[{"name":"보안 신고","aliases":[]}]', name="list_menus",
                    tool_call_id="1"),
        ToolMessage(content=[{"type": "text", "text": SEARCH}], name="search_similar_vocs",
                    tool_call_id="2"),
        ToolMessage(content="ok", name="JudgeResult", tool_call_id="3"),
    ]


def test_tool_results_skip_judge_result():
    tr = judge_agent._tool_results(msgs())
    assert [t["name"] for t in tr] == ["list_menus", "search_similar_vocs"]
    assert tr[1]["content"] == SEARCH  # 블록 리스트도 문자열로


def test_retrieved_parses_search_results():
    tr = judge_agent._tool_results(msgs())
    assert judge_agent._retrieved(tr) == [
        {"id": 3, "voc_text": "보안 신고 접수", "menus": ["보안 신고"], "similarity": 0.71}]


def test_retrieved_ignores_bad_json_and_duplicates():
    tr = [{"name": "search_similar_vocs", "content": "not json"},
          {"name": "search_similar_vocs", "content": SEARCH},
          {"name": "search_similar_vocs", "content": SEARCH}]
    assert [r["id"] for r in judge_agent._retrieved(tr)] == [3]
