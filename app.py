"""VOC 접수 판단·응답 보조 Streamlit 앱. 실행: streamlit run app.py"""
import streamlit as st

from voc import db as vocdb
from voc.service import process_voc


def render_result(result):
    """판정 결과를 화면에 표시한다."""
    if "error" in result:
        st.warning(result["error"])
        return
    if result["is_processable"]:
        st.success("판정: 처리 가능")
        st.write("매칭된 메뉴: " + ", ".join(result["matched_menus"]))
        st.write("메뉴별 누적 횟수:", result["menu_counts"])
        if result["is_frequent"]:
            st.info("자주 들어오는 VOC (누적 3회 이상)")
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
        st.subheader("안내 문구 초안")
        st.text_area("초안", result["guidance_draft"] or "", height=160)


def main():
    st.title("VOC 접수 판단·응답 보조")
    try:
        menus = vocdb.load_menus()
    except Exception as e:  # 설정 파일 오류: 판정을 막고 오류 표시
        st.error(f"메뉴 설정 파일을 읽을 수 없습니다: {e}")
        return
    conn = vocdb.connect()
    vocdb.init_db(conn, menus=menus)
    with st.form("voc_form"):
        voc_text = st.text_area("VOC 본문")
        registrant_id = st.text_input("등록자 ID")
        submitted = st.form_submit_button("제출")
    if submitted:
        try:
            render_result(process_voc(conn, voc_text, registrant_id, menus=menus))
        except Exception as e:  # 화면이 깨지지 않도록 오류 표시
            st.error(f"처리 중 오류가 발생했습니다: {e}")
    with st.expander("VOC 이력"):
        rows = conn.execute(
            "SELECT id, registrant_id, voc_text, is_processable, matched_menus "
            "FROM voc_history ORDER BY id DESC LIMIT 50").fetchall()
        st.dataframe([dict(r) for r in rows])
    conn.close()


main()
