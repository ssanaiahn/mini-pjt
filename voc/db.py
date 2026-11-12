"""SQLite 모의 DB: VOC 이력, 메뉴별 누적, 사용자/계정, 업무 데이터."""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "voc.db"
MENUS_PATH = ROOT / "config" / "menus.json"

MOCK_USERS = [
    ("u001", "김하나", "u001@example.com", "GOLD"),
    ("u002", "이둘", "u002@example.com", "SILVER"),
    ("u003", "박셋", "u003@example.com", "GOLD"),
    ("u004", "최넷", "u004@example.com", "BRONZE"),
    ("u005", "정다섯", "u005@example.com", "SILVER"),
    ("u006", "한여섯", "u006@example.com", "BRONZE"),
    # 앱 테스트 이력의 등록자(2026-11-12 반영). 가짜 이메일·등급.
    ("가나다", "가나다", "ganada@example.com", "GOLD"),
    ("나라바", "나라바", "naraba@example.com", "SILVER"),
    ("라마바", "라마바", "ramaba@example.com", "BRONZE"),
    ("사아자", "사아자", "saaja@example.com", "GOLD"),
    ("마바사", "마바사", "mabasa@example.com", "SILVER"),
    ("가다마", "가다마", "gadama@example.com", "BRONZE"),
    ("abc", "abc", "abc@example.com", "SILVER"),
    # 시연용 추가 모의 사용자 20명(2026-11-12). 가짜 이메일·등급.
    ("def", "def", "def@example.com", "GOLD"),
    ("ghi", "ghi", "ghi@example.com", "SILVER"),
    ("jkl", "jkl", "jkl@example.com", "BRONZE"),
    ("mno", "mno", "mno@example.com", "GOLD"),
    ("pqr", "pqr", "pqr@example.com", "SILVER"),
    ("stu", "stu", "stu@example.com", "BRONZE"),
    ("vwx", "vwx", "vwx@example.com", "GOLD"),
    ("aaa", "aaa", "aaa@example.com", "SILVER"),
    ("bbb", "bbb", "bbb@example.com", "BRONZE"),
    ("ccc", "ccc", "ccc@example.com", "GOLD"),
    ("ddd", "ddd", "ddd@example.com", "SILVER"),
    ("eee", "eee", "eee@example.com", "BRONZE"),
    ("다나가", "다나가", "danaga@example.com", "GOLD"),
    ("아차파", "아차파", "achapa@example.com", "SILVER"),
    ("하카타", "하카타", "hakata@example.com", "BRONZE"),
    ("파타카", "파타카", "pataka@example.com", "GOLD"),
    ("자차카", "자차카", "jachaka@example.com", "SILVER"),
    ("바사아", "바사아", "basaa@example.com", "BRONZE"),
    ("다라마", "다라마", "darama@example.com", "GOLD"),
    ("타파하", "타파하", "tapaha@example.com", "SILVER"),
]


# 모의 처리 내용: 실제 처리 기록이 없어 메뉴별로 대략적인 처리 방식을 만들어 둔다(화면에 "(모의)" 표시).
MOCK_HANDLING = {
    "보안 공지": "해당 보안 공지 링크와 패치 적용 가이드를 회신",
    "정보보호 규정": "관련 규정 조항과 최신 가이드 문서 위치를 안내",
    "보안 신고": "보안관제팀으로 이관하고, 의심 메일 차단과 비밀번호 변경 방법을 안내",
    "개선 제안": "검토 부서에 전달해 차기 개선 과제로 등록하고 결과를 회신",
    "비밀유지계약": "부서별 서약서 서명 현황을 엑셀로 추출해 회신",
    "사용자 관리": "권한 신청 내용을 확인해 권한을 부여하고 처리 완료 메일을 발송",
}
MOCK_HANDLING_DEFAULT = "담당자가 내용을 확인해 처리하고 결과를 회신"


def load_menus(path=None):
    with open(path or os.environ.get("VOC_MENUS_PATH") or MENUS_PATH, encoding="utf-8") as f:
        menus = json.load(f)["menus"]
    if not isinstance(menus, list):
        raise ValueError("menus 설정 형식이 올바르지 않습니다")
    validate_menus(menus)
    return menus


def load_policies(path=None):
    """서비스 정책 목록 [{id, description, patterns, message}]. 없으면 빈 목록."""
    with open(path or os.environ.get("VOC_MENUS_PATH") or MENUS_PATH, encoding="utf-8") as f:
        return json.load(f).get("policies", [])


def normalize(text):
    """공백을 모두 제거하고 영문을 소문자로 바꾼다."""
    return "".join((text or "").split()).lower()


def validate_menus(menus):
    """같은 메뉴명/별칭이 서로 다른 두 메뉴에 있으면 ValueError."""
    owner = {}
    for m in menus:
        for term in [m["name"], *m.get("aliases", [])]:
            key = normalize(term)
            if owner.setdefault(key, m["name"]) != m["name"]:
                raise ValueError(
                    f"중복 등록된 메뉴명/별칭 '{term}': {owner[key]} / {m['name']}")


def connect(db_path=None):
    """DB 경로: 인자 > 환경변수 VOC_DB_PATH > 기본 data/voc.db. 없으면 파일/폴더 생성."""
    db_path = db_path or os.environ.get("VOC_DB_PATH") or DEFAULT_DB
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn, reset=False, menus=None):
    """테이블을 만들고 모의 데이터를 채운다. reset=True면 모두 비우고 다시 시드."""
    menus = menus or load_menus()
    if reset:
        conn.execute("DROP VIEW IF EXISTS menu_counts")
        for t in ("voc_menu_matches", "voc_history", "users", "business_data"):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS voc_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            registrant_id TEXT NOT NULL,
            voc_text TEXT NOT NULL,
            is_processable INTEGER NOT NULL,
            matched_menus TEXT NOT NULL,
            guidance_draft TEXT,
            guidance_source TEXT,
            created_at TEXT NOT NULL,
            match_source TEXT,
            similar_voc_id INTEGER,
            similarity REAL,
            judge_reason TEXT);
        CREATE TABLE IF NOT EXISTS voc_menu_matches(
            voc_id INTEGER NOT NULL REFERENCES voc_history(id),
            menu TEXT NOT NULL,
            PRIMARY KEY (voc_id, menu));
        -- 누적은 저장하지 않고 이력(처리 가능 건의 매칭 기록)에서 매번 계산
        CREATE VIEW IF NOT EXISTS menu_counts AS
            SELECT menu, COUNT(*) AS count FROM voc_menu_matches GROUP BY menu;
        CREATE TABLE IF NOT EXISTS users(
            user_id TEXT PRIMARY KEY, name TEXT, email TEXT, grade TEXT);
        CREATE TABLE IF NOT EXISTS business_data(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, menu TEXT, title TEXT, status TEXT);
        """
    )
    _migrate(conn)
    # 없는 모의 사용자만 채운다(기존 DB를 다시 열 때 새로 추가된 사용자도 반영, 중복 없음)
    have = {r[0] for r in conn.execute("SELECT user_id FROM users")}
    for user in MOCK_USERS:
        uid = user[0]
        if uid in have:
            continue
        conn.execute("INSERT INTO users VALUES (?,?,?,?)", user)
        for m in menus:
            conn.execute(
                "INSERT INTO business_data(user_id, menu, title, status) VALUES (?,?,?,?)",
                (uid, m["name"], f"{m['name']} 샘플 건 ({uid})", "완료"),
            )
    conn.commit()


def backfill_mock_handling(conn):
    """처리 가능 건 중 처리 내용이 없는 건에 모의 처리 내용을 채운다(처리일 = 접수 다음 날).

    앱 시작(매 화면 실행) 때 호출한다. 이미 처리 내용이 있는 건과 처리 불가 건은 건드리지 않는다.
    반환: 채운 건수.
    """
    from datetime import date, timedelta

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


def _migrate(conn):
    """이전 버전 DB에 유사 VOC 판정용 컬럼이 없으면 추가한다(기존 이력 유지)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(voc_history)")}
    for name, typ in (("match_source", "TEXT"), ("similar_voc_id", "INTEGER"),
                      ("similarity", "REAL"), ("judge_reason", "TEXT"),
                      ("handling_note", "TEXT"), ("handled_at", "TEXT")):
        if name not in cols:
            conn.execute(f"ALTER TABLE voc_history ADD COLUMN {name} {typ}")
