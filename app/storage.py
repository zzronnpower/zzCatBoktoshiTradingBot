import sqlite3
from typing import Any, Dict, List


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                action TEXT NOT NULL,
                coin TEXT,
                side TEXT,
                margin REAL,
                leverage REAL,
                status TEXT,
                notes TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                balance REAL NOT NULL,
                available REAL NOT NULL,
                locked REAL NOT NULL,
                unrealized REAL NOT NULL,
                total_equity REAL NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                coin TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                signal INTEGER NOT NULL,
                details TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def add_log(db_path: str, ts: int, level: str, message: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO logs (ts, level, message) VALUES (?, ?, ?)", (ts, level, message))
        conn.commit()
    finally:
        conn.close()


def get_logs(db_path: str, limit: int = 100) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT ts, level, message FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        return [{"ts": row[0], "level": row[1], "message": row[2]} for row in rows]
    finally:
        conn.close()


def add_trade(
    db_path: str,
    ts: int,
    action: str,
    coin: str,
    side: str,
    margin: float,
    leverage: float,
    status: str,
    notes: str,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (ts, action, coin, side, margin, leverage, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, action, coin, side, margin, leverage, status, notes),
        )
        conn.commit()
    finally:
        conn.close()


def get_trades(db_path: str, limit: int = 100) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ts, action, coin, side, margin, leverage, status, notes
            FROM trades ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "ts": row[0],
                "action": row[1],
                "coin": row[2],
                "side": row[3],
                "margin": row[4],
                "leverage": row[5],
                "status": row[6],
                "notes": row[7],
            }
            for row in rows
        ]
    finally:
        conn.close()


def add_equity_snapshot(
    db_path: str,
    ts: int,
    balance: float,
    available: float,
    locked: float,
    unrealized: float,
    total_equity: float,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO equity_curve (ts, balance, available, locked, unrealized, total_equity)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, balance, available, locked, unrealized, total_equity),
        )
        conn.commit()
    finally:
        conn.close()


def get_equity_curve(db_path: str, limit: int = 500) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ts, balance, available, locked, unrealized, total_equity
            FROM equity_curve ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "ts": row[0],
                "balance": row[1],
                "available": row[2],
                "locked": row[3],
                "unrealized": row[4],
                "total_equity": row[5],
            }
            for row in rows
        ]
    finally:
        conn.close()


def add_signal(db_path: str, ts: int, coin: str, timeframe: str, signal: bool, details: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO signals (ts, coin, timeframe, signal, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts, coin, timeframe, 1 if signal else 0, details),
        )
        conn.commit()
    finally:
        conn.close()


def get_signals(db_path: str, limit: int = 200) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ts, coin, timeframe, signal, details
            FROM signals ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "ts": row[0],
                "coin": row[1],
                "timeframe": row[2],
                "signal": bool(row[3]),
                "details": row[4],
            }
            for row in rows
        ]
    finally:
        conn.close()


def set_kv(db_path: str, key: str, value: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_kv(db_path: str, key: str, default: str = "") -> str:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM kv WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def get_all_kv(db_path: str) -> Dict[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM kv")
        rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()
