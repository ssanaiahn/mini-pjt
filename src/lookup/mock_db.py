"""[lookup] 모의 DB 조회(화면 표시용): 등록자 계정과 반복 메뉴의 업무 데이터. 사내 DB 대신 SQLite 모의 데이터."""


def lookup_mock_db(conn, registrant_id, frequent_menus):
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (registrant_id,)).fetchone()
    account = {"found": True, "account": dict(u)} if u else {"found": False, "account": None}
    qs = ",".join("?" * len(frequent_menus))
    rows = conn.execute(
        f"SELECT * FROM business_data WHERE user_id=? AND menu IN ({qs}) ORDER BY id",
        (registrant_id, *frequent_menus)).fetchall()
    return account, [dict(r) for r in rows]
