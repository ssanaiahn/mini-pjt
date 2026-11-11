"""SQLite 모의 DB: VOC 이력, 메뉴별 누적, 사용자/계정, 업무 데이터."""
import json
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


def load_menus(path=MENUS_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["menus"]


def connect(db_path=DEFAULT_DB):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn, reset=False, menus=None):
    """테이블을 만들고 모의 데이터를 채운다. reset=True면 모두 비우고 다시 시드."""
    menus = menus or load_menus()
    if reset:
        for t in ("voc_history", "menu_counts", "users", "business_data"):
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS menu_counts(
            menu TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);
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
