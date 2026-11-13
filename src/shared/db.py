"""[shared] SQLite 연결·스키마·모의 데이터(사용자/계정, 업무 데이터) 시드.

VOC 이력 저장·누적 계산은 records 도메인, 메뉴 설정 로딩은 shared/config.py가 맡는다.
"""
import os
import sqlite3
from pathlib import Path

from .config import load_menus
from .llm import ROOT

DEFAULT_DB = ROOT / "data" / "voc.db"

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


def _migrate(conn):
    """이전 버전 DB에 유사 VOC 판정용 컬럼이 없으면 추가한다(기존 이력 유지)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(voc_history)")}
    for name, typ in (("match_source", "TEXT"), ("similar_voc_id", "INTEGER"),
                      ("similarity", "REAL"), ("judge_reason", "TEXT"),
                      ("handling_note", "TEXT"), ("handled_at", "TEXT")):
        if name not in cols:
            conn.execute(f"ALTER TABLE voc_history ADD COLUMN {name} {typ}")
