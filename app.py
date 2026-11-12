"""VOC 접수 판단·응답 보조 Streamlit 앱. 실행: streamlit run app.py"""
import streamlit as st

from voc import db as vocdb
from voc import llm
from voc.service import process_voc

STEP_LABELS = {"validate": "입력 검증", "guard": "개인정보 가리기", "policy_check": "서비스 정책 확인",
               "rule_match": "메뉴명 확인", "agent_judge": "판정 에이전트",
               "similar_fallback": "글자 유사도", "guidance": "안내 문구", "record": "저장·누적",
               "history": "유사 VOC 이력", "lookup": "조회"}
SOURCE_LABELS = {"menu": "본문의 메뉴명·별칭", "similar": "과거 VOC 글자 유사도",
                 "agent": "판정 에이전트(Claude)", "policy": "서비스 정책(국내 임직원 전용)"}
GUIDANCE_LABELS = {"claude": "Claude 생성", "policy": "정책 고정 문구"}


def render_judgement(result):
    """판정 근거: 개인정보 가리기, 판정 방식, 에이전트 근거·도구, 그래프 경로."""
    if result.get("pii_found"):
        st.info("개인정보(" + ", ".join(result["pii_found"]) + ")를 가린 뒤 저장했습니다: "
                + result["voc_text"])
    src = result.get("match_source")
    if src:
        st.caption("판정 방식: " + SOURCE_LABELS[src])
    sim = result.get("similar_voc")
    if src == "similar" and sim:
        st.info(f"본문에 메뉴명이 없어 과거 VOC #{sim['id']}와의 유사도"
                f"({sim['similarity']:.2f})로 판정했습니다: \"{sim['voc_text']}\"")
    judge = result.get("judge")
    if judge:
        st.info("에이전트 판단 근거: " + judge["reason"])
        if judge.get("tool_calls"):
            st.caption("에이전트가 사용한 MCP 도구: " + " → ".join(judge["tool_calls"]))
    if result.get("agent_error"):
        st.caption("에이전트를 사용할 수 없어 규칙 기반으로 판정했습니다 ("
                   + result["agent_error"][:80] + ")")
    st.caption("처리 경로: " + " → ".join(STEP_LABELS.get(s, s) for s in result.get("steps", [])))


def render_history(history):
    """같은 메뉴의 비슷한 과거 VOC와 처리 내용(담당자 참고용)."""
    st.subheader("유사 VOC 처리 이력")
    if not history:
        st.caption("같은 메뉴로 접수된 비슷한 과거 VOC가 없습니다.")
        return
    if any(h["same_registrant"] for h in history):
        st.info("같은 등록자가 비슷한 내용을 이전에도 접수했습니다. 기존 처리 내용을 참고하세요.")
    st.dataframe([{
        "접수일": (h["created_at"] or "")[:10],
        "등록자": h["registrant_id"] + (" (같은 등록자)" if h["same_registrant"] else ""),
        "내용": h["voc_text"], "처리 내용": h["handling_note"] or "처리 전",
        "처리일": h["handled_at"] or "-", "유사도": h["similarity"]} for h in history],
        hide_index=True)
    st.caption('처리 내용의 "(모의)"는 실제 처리 기록이 없어 만든 예시입니다.')


def render_result(result):
    """판정 결과를 화면에 표시한다."""
    if "error" in result:
        st.warning(result["error"])
        return
    if result["is_processable"]:
        st.success("판정: 처리 가능")
        render_judgement(result)
        st.write("매칭된 메뉴: " + ", ".join(result["matched_menus"]))
        st.write("메뉴별 누적 횟수:", result["menu_counts"])
        render_history(result.get("similar_history") or [])
        if result["is_frequent"]:
            st.info("자주 들어오는 VOC (누적 3회 이상)")
            summary = result.get("lookup_summary") or {}
            if summary.get("summary"):
                st.subheader("조회 에이전트 요약")
                st.write(summary["summary"])
                st.caption("사용한 MCP 도구: " + " → ".join(summary.get("tool_calls", [])))
            elif summary.get("error"):
                st.caption("조회 에이전트를 사용할 수 없어 조회 결과만 표시합니다 ("
                           + summary["error"][:80] + ")")
            st.subheader("등록자 계정 정보")
            acc = result["account_info"] or {}
            if acc.get("found"):
                st.json(acc["account"])
            else:
                st.warning("등록자 정보 없음")
            st.subheader("업무 데이터")
            st.write("조회 대상 메뉴: " + ", ".join(result["frequent_menus"]))
            if result["business_data"]:
                st.dataframe(result["business_data"])
            else:
                st.write("조회된 업무 데이터가 없습니다.")
    else:
        st.error("판정: 처리 불가")
        render_judgement(result)
        st.subheader("안내 문구 초안")
        source = GUIDANCE_LABELS.get(result["guidance_source"], "템플릿")
        st.caption(f"문구 출처: {source}")
        st.text_area("초안", result["guidance_draft"] or "", height=160)


def main():
    llm.load_env()
    st.title("VOC 접수 판단·응답 보조")
    if llm.llm_enabled():
        st.sidebar.success("Claude(Bedrock) 사용 중\n\n판정 에이전트·조회 에이전트·MCP 도구 활성")
    else:
        st.sidebar.warning("규칙 모드\n\nAWS 자격 증명이 없어 메뉴명·글자 유사도·템플릿으로만 동작합니다.")
    try:
        menus = vocdb.load_menus()
    except Exception as e:  # 설정 파일 오류: 판정을 막고 오류 표시
        st.error(f"메뉴 설정 파일을 읽을 수 없습니다: {e}")
        return
    st.sidebar.caption("등록 메뉴: " + ", ".join(m["name"] for m in menus))
    conn = vocdb.connect()
    vocdb.init_db(conn, menus=menus)
    vocdb.backfill_mock_handling(conn)  # 처리 기록이 없는 과거 접수 건에 모의 처리 내용
    with st.form("voc_form"):
        voc_text = st.text_area("VOC 본문")
        registrant_id = st.text_input("등록자 ID")
        submitted = st.form_submit_button("제출")
    if submitted:
        try:
            with st.spinner("판정 중..."):
                result = process_voc(conn, voc_text, registrant_id, menus=menus)
            render_result(result)
        except Exception as e:  # 화면이 깨지지 않도록 오류 표시
            st.error(f"처리 중 오류가 발생했습니다: {e}")
    with st.expander("VOC 이력"):
        rows = conn.execute(
            "SELECT id, registrant_id, voc_text, is_processable, matched_menus, "
            "match_source, similar_voc_id, similarity, judge_reason, handling_note, handled_at "
            "FROM voc_history ORDER BY id DESC LIMIT 50").fetchall()
        st.dataframe([dict(r) for r in rows])
    conn.close()


main()
