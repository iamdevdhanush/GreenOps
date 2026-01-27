import sqlite3
from pathlib import Path

DB_PATH = Path("greenops.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id TEXT,
            idle_minutes REAL,
            action TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

