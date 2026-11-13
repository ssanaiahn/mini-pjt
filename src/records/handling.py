"""[records] 처리 내용(모의): 실제 처리 기록이 없어 메뉴별 대략적인 처리 방식을 채운다."""
from datetime import date, timedelta

MOCK_HANDLING = {
    "보안 공지": "해당 보안 공지 링크와 패치 적용 가이드를 회신",
    "정보보호 규정": "관련 규정 조항과 최신 가이드 문서 위치를 안내",
    "보안 신고": "보안관제팀으로 이관하고, 의심 메일 차단과 비밀번호 변경 방법을 안내",
    "개선 제안": "검토 부서에 전달해 차기 개선 과제로 등록하고 결과를 회신",
    "비밀유지계약": "부서별 서약서 서명 현황을 엑셀로 추출해 회신",
    "사용자 관리": "권한 신청 내용을 확인해 권한을 부여하고 처리 완료 메일을 발송",
}
MOCK_HANDLING_DEFAULT = "담당자가 내용을 확인해 처리하고 결과를 회신"


def backfill_mock_handling(conn):
    """처리 가능 건 중 처리 내용이 없는 건에 모의 처리 내용을 채운다(처리일 = 접수 다음 날).

    앱 시작(매 화면 실행) 때 호출한다. 이미 처리 내용이 있는 건과 처리 불가 건은 건드리지 않는다.
    반환: 채운 건수.
    """
    rows = conn.execute("SELECT id, matched_menus, created_at FROM voc_history"
                        " WHERE is_processable=1 AND handling_note IS NULL").fetchall()
    for r in rows:
        menu = (r["matched_menus"] or "").split("|")[0]
        try:
            handled = (date.fromisoformat(r["created_at"][:10]) + timedelta(days=1)).isoformat()
        except (TypeError, ValueError):
            handled = (r["created_at"] or "")[:10]
        conn.execute("UPDATE voc_history SET handling_note=?, handled_at=? WHERE id=?",
                     ("(모의) " + MOCK_HANDLING.get(menu, MOCK_HANDLING_DEFAULT), handled, r["id"]))
    conn.commit()
    return len(rows)
