"""VOC 접수 판단·응답 보조 Streamlit 앱. 실행: streamlit run app.py

화면 디자인: UI/UX Pro Max 추천 "Minimalism & Swiss Style"(업무용 도구) — 테마는
.streamlit/config.toml, 아이콘은 Material Symbols, 상태는 색 + 아이콘 + 글자로 함께 표시.
"""
import os

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


def render_verdict(result):
    """판정 카드: 상태(색·아이콘·글자), 메뉴, 판정 방식·근거, 처리 경로."""
    with st.container(border=True):
        src = result.get("match_source")
        if result["is_processable"]:
            st.success("판정: 처리 가능", icon=":material/check_circle:")
            with st.container(horizontal=True):
                for m in result["matched_menus"]:
                    st.badge(m, icon=":material/folder_open:", color="blue")
        elif src == "policy":
            st.error("판정: 처리 불가 · 서비스 정책", icon=":material/block:")
        else:
            st.error("판정: 처리 불가", icon=":material/cancel:")

        if src:
            st.caption("판정 방식: " + SOURCE_LABELS.get(src, src))
        if result.get("pii_found"):
            st.info("개인정보(" + ", ".join(result["pii_found"]) + ")를 가린 뒤 저장했습니다: "
                    + result["voc_text"], icon=":material/shield_lock:")
        sim = result.get("similar_voc")
        if src == "similar" and sim:
            st.info(f"본문에 메뉴명이 없어 과거 VOC #{sim['id']}와의 유사도"
                    f"({sim['similarity']:.2f})로 판정했습니다: \"{sim['voc_text']}\"",
                    icon=":material/compare_arrows:")
        judge = result.get("judge")
        if judge:
            st.markdown(f"**판단 근거** {judge['reason']}")
            if judge.get("tool_calls"):
                st.caption("사용한 도구: " + " › ".join(judge["tool_calls"]))
        if result.get("agent_error"):
            st.caption("판정 에이전트를 사용할 수 없어 규칙 기반으로 판정했습니다 ("
                       + result["agent_error"][:80] + ")")
        st.caption("처리 경로: " + " › ".join(STEP_LABELS.get(s, s) for s in result.get("steps", [])))


def render_counts(result):
    with st.container(horizontal=True):
        for menu, n in result["menu_counts"].items():
            st.metric(f"{menu} 누적", f"{n}건", border=True,
                      help="등록자와 관계없이 이 메뉴로 접수된 처리 가능 VOC 수")
    if result["is_frequent"]:
        st.badge("자주 들어오는 VOC (누적 3회 이상)", icon=":material/repeat:", color="orange")


def render_history(history):
    """같은 메뉴의 비슷한 과거 VOC와 처리 내용(담당자 참고용)."""
    with st.container(border=True):
        st.subheader("유사 VOC 처리 이력", icon=":material/history:", anchor=False)
        if not history:
            st.caption("같은 메뉴로 접수된 비슷한 과거 VOC가 없습니다.")
            return
        if any(h["same_registrant"] for h in history):
            st.info("같은 등록자가 비슷한 내용을 이전에도 접수했습니다. 기존 처리 내용을 참고하세요.",
                    icon=":material/person_search:")
        st.dataframe([{
            "접수일": (h["created_at"] or "")[:10],
            "등록자": h["registrant_id"] + (" (같은 등록자)" if h["same_registrant"] else ""),
            "내용": h["voc_text"], "처리 내용": h["handling_note"] or "처리 전",
            "처리일": h["handled_at"] or "-", "유사도": h["similarity"]} for h in history],
            hide_index=True, alt="같은 메뉴로 접수된 비슷한 과거 VOC와 처리 내용",
            column_config={"유사도": st.column_config.ProgressColumn(
                "유사도", min_value=0.0, max_value=1.0, format="%.2f")})
        st.caption('처리 내용의 "(모의)"는 실제 처리 기록이 없어 만든 예시입니다.')


def render_lookup(result):
    """누적 3회 이상: 조회 에이전트 요약 + 모의 DB 계정·업무 데이터."""
    with st.container(border=True):
        st.subheader("반복 접수 조회", icon=":material/manage_search:", anchor=False)
        summary = result.get("lookup_summary") or {}
        if summary.get("summary"):
            st.markdown(summary["summary"])
            st.caption("사용한 MCP 도구: " + " › ".join(summary.get("tool_calls", [])))
        elif summary.get("error"):
            st.caption("조회 에이전트를 사용할 수 없어 조회 결과만 표시합니다 ("
                       + summary["error"][:80] + ")")
        st.subheader("등록자 계정 정보", anchor=False)
        acc = result["account_info"] or {}
        if acc.get("found"):
            a = acc["account"]
            with st.container(horizontal=True):
                st.badge(f"{a['name']} ({a['user_id']})", icon=":material/person:", color="gray")
                st.badge(a["grade"], icon=":material/workspace_premium:", color="blue")
                st.badge(a["email"], icon=":material/mail:", color="gray")
        else:
            st.warning("등록자 정보 없음", icon=":material/person_off:")
        st.subheader("업무 데이터", anchor=False)
        st.caption("조회 대상 메뉴: " + ", ".join(result["frequent_menus"]))
        if result["business_data"]:
            st.dataframe(result["business_data"], hide_index=True,
                         alt="등록자의 메뉴별 업무 데이터(모의)")
        else:
            st.write("조회된 업무 데이터가 없습니다.")


def render_guidance(result):
    with st.container(border=True):
        st.subheader("안내 문구 초안", icon=":material/edit_note:", anchor=False)
        source = GUIDANCE_LABELS.get(result["guidance_source"], "템플릿")
        st.caption(f"문구 출처: {source} · 담당자가 확인하고 고친 뒤 보내 주세요(자동 발송하지 않음)")
        st.text_area("초안", result["guidance_draft"] or "", height=160)


def render_result(result):
    """판정 결과를 화면에 표시한다."""
    if "error" in result:
        st.warning(result["error"], icon=":material/warning:")
        return
    render_verdict(result)
    if result["is_processable"]:
        render_counts(result)
        render_history(result.get("similar_history") or [])
        if result["is_frequent"]:
            render_lookup(result)
    else:
        render_guidance(result)


def render_sidebar(menus):
    with st.sidebar:
        if llm.llm_enabled():
            st.badge("Claude 사용 중", icon=":material/smart_toy:", color="green")
            st.caption("모델: " + (os.environ.get("VOC_BEDROCK_MODEL") or llm.CHAT_MODEL)
                       + "\n\n판정 에이전트 · 조회 에이전트 · MCP 도구")
        else:
            st.badge("규칙 모드", icon=":material/rule:", color="orange")
            st.caption("AWS 자격 증명이 없거나 LLM 사용이 꺼져 있어(VOC_USE_LLM=0) "
                       "메뉴명·글자 유사도·템플릿으로만 동작합니다.")
        st.subheader("등록 메뉴", anchor=False)
        with st.container(horizontal=True):
            for m in menus:
                st.badge(m["name"], color="blue")
        st.subheader("서비스 정책", anchor=False)
        st.caption("국내 임직원 전용 포털입니다. 해외 법인 임직원의 사용·접속 요청은 정책 문구로 종료합니다.")
        st.caption("개인정보(주민번호·전화번호·이메일)는 저장·LLM 전달 전에 가립니다.")


def main():
    st.set_page_config(page_title="VOC 접수 판단", page_icon=":material/support_agent:")
    llm.load_env()
    st.title("VOC 접수 판단·응답 보조", icon=":material/support_agent:", anchor=False)
    st.caption("VOC를 접수할지, 어느 메뉴인지 판단하고, 처리할 수 없는 건은 안내 문구 초안을 만듭니다.")
    try:
        menus = vocdb.load_menus()
    except Exception as e:  # 설정 파일 오류: 판정을 막고 오류 표시
        st.error(f"메뉴 설정 파일을 읽을 수 없습니다: {e}", icon=":material/error:")
        return
    render_sidebar(menus)
    conn = vocdb.connect()
    vocdb.init_db(conn, menus=menus)
    vocdb.backfill_mock_handling(conn)  # 처리 기록이 없는 과거 접수 건에 모의 처리 내용
    with st.form("voc_form"):
        voc_text = st.text_area("VOC 본문", key="voc_text", placeholder="예: 서약서 제출 현황을 부서별로 받고 싶습니다",
                                help="주민번호·전화번호·이메일은 저장하기 전에 자동으로 가려집니다.")
        registrant_id = st.text_input("등록자 ID", key="registrant_id", placeholder="예: u001, 가나다",
                                      help="모의 사용자(u001~u006, 가나다, 나라바 등)면 계정·업무 데이터가 조회됩니다.")
        submitted = st.form_submit_button("판정하기", key="submit", icon=":material/send:",
                                          type="primary")
    if submitted:
        try:
            with st.spinner("판정 중..."):
                result = process_voc(conn, voc_text, registrant_id, menus=menus)
            render_result(result)
        except Exception as e:  # 화면이 깨지지 않도록 오류 표시
            st.error(f"처리 중 오류가 발생했습니다: {e}", icon=":material/error:")
    with st.expander("VOC 이력 (최근 50건)", icon=":material/list_alt:"):
        rows = conn.execute(
            "SELECT id, created_at, registrant_id, voc_text, is_processable, matched_menus, "
            "match_source, judge_reason, handling_note, handled_at "
            "FROM voc_history ORDER BY id DESC LIMIT 50").fetchall()
        st.dataframe([dict(r) for r in rows], hide_index=True, alt="최근 VOC 이력 50건",
                     column_config={
                         "id": "번호", "created_at": "접수 시각", "registrant_id": "등록자",
                         "voc_text": "내용",
                         "is_processable": st.column_config.CheckboxColumn("처리 가능"),
                         "matched_menus": "메뉴", "match_source": "판정 방식",
                         "judge_reason": "판단 근거", "handling_note": "처리 내용",
                         "handled_at": "처리일"})
    conn.close()


main()
