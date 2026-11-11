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
]


def load_menus(path=None):
    with open(path or os.environ.get("VOC_MENUS_PATH") or MENUS_PATH, encoding="utf-8") as f:
        menus = json.load(f)["menus"]
    if not isinstance(menus, list):
        raise ValueError("menus 설정 형식이 올바르지 않습니다")
    validate_menus(menus)
    return menus


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
            created_at TEXT NOT NULL);
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
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.executemany("INSERT INTO users VALUES (?,?,?,?)", MOCK_USERS)
        for uid, *_ in MOCK_USERS:
            for m in menus:
                conn.execute(
                    "INSERT INTO business_data(user_id, menu, title, status) VALUES (?,?,?,?)",
                    (uid, m["name"], f"{m['name']} 샘플 건 ({uid})", "완료"),
                )
    conn.commit()
