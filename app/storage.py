import json
import sqlite3
from typing import Any, Dict, List, Tuple


MAX_LOG_ROWS = 100
MAX_SIGNAL_ROWS = 100
MAX_EQUITY_ROWS = 100
SQLITE_BUSY_TIMEOUT_MS = 5000
FINALIZATION_STATES = {"PENDING", "ESTIMATED", "FINALIZED"}
ESTIMATED_SOURCES = {"none", "snapshot", "market_hint", "formula"}


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def _trim_table_by_id(cur: sqlite3.Cursor, table: str, max_rows: int) -> None:
    safe_max = max(1, int(max_rows))
    cur.execute(
        f"""
        DELETE FROM {table}
        WHERE id NOT IN (
            SELECT id FROM {table}
            ORDER BY id DESC
            LIMIT ?
        )
        """,
        (safe_max,),
    )


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall()
    out: set[str] = set()
    for row in rows:
        if len(row) >= 2 and row[1]:
            out.add(str(row[1]))
    return out


def _derive_finalization_fields(realized_pnl: Any, exit_price: Any, raw_text: Any) -> Tuple[str, str]:
    try:
        realized = float(realized_pnl)
        if realized == realized:  # not NaN
            return "FINALIZED", "none"
    except (TypeError, ValueError):
        pass

    raw_obj: Dict[str, Any] = {}
    try:
        parsed = json.loads(str(raw_text or "{}"))
        if isinstance(parsed, dict):
            raw_obj = parsed
    except Exception:
        raw_obj = {}

    existing_state = str(raw_obj.get("finalization_state", "") or "").upper().strip()
    if existing_state in FINALIZATION_STATES:
        existing_source = str(raw_obj.get("estimated_source", "none") or "none").strip().lower()
        if existing_source not in ESTIMATED_SOURCES:
            existing_source = "none"
        if existing_state == "FINALIZED":
            return "FINALIZED", "none"
        return existing_state, existing_source

    close_snapshot = raw_obj.get("close_snapshot") if isinstance(raw_obj.get("close_snapshot"), dict) else {}
    if isinstance(close_snapshot, dict):
        for key in ("realizedPnl", "unrealizedPnl", "pnl"):
            val = close_snapshot.get(key)
            if val is None:
                continue
            try:
                parsed = float(val)
                if parsed == parsed:  # not NaN
                    return "ESTIMATED", "snapshot"
            except (TypeError, ValueError):
                continue

    if exit_price is not None:
        try:
            maybe_exit = float(exit_price)
            if maybe_exit == maybe_exit and maybe_exit > 0:
                return "ESTIMATED", "formula"
        except (TypeError, ValueError):
            pass

    return "PENDING", "none"


def _ensure_journal_finalization_schema(cur: sqlite3.Cursor) -> None:
    columns = _table_columns(cur, "journal_entries")
    if "finalization_state" not in columns:
        cur.execute("ALTER TABLE journal_entries ADD COLUMN finalization_state TEXT NOT NULL DEFAULT 'PENDING'")
    if "estimated_source" not in columns:
        cur.execute("ALTER TABLE journal_entries ADD COLUMN estimated_source TEXT NOT NULL DEFAULT 'none'")

    cur.execute(
        """
        SELECT id, realized_pnl, exit_price, raw, finalization_state, estimated_source
        FROM journal_entries
        """
    )
    rows = cur.fetchall()
    for row in rows:
        row_id = int(row[0])
        current_state = str(row[4] or "").upper().strip()
        current_source = str(row[5] or "none").lower().strip()
        needs_backfill = current_state not in FINALIZATION_STATES or current_source not in ESTIMATED_SOURCES
        if not needs_backfill:
            continue
        next_state, next_source = _derive_finalization_fields(row[1], row[2], row[3])
        cur.execute(
            "UPDATE journal_entries SET finalization_state = ?, estimated_source = ? WHERE id = ?",
            (next_state, next_source, row_id),
        )


def trim_runtime_tables(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        _trim_table_by_id(cur, "logs", MAX_LOG_ROWS)
        _trim_table_by_id(cur, "signals", MAX_SIGNAL_ROWS)
        _trim_table_by_id(cur, "equity_curve", MAX_EQUITY_ROWS)
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT NOT NULL UNIQUE,
                close_ts INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT,
                qty REAL,
                entry_price REAL,
                exit_price REAL,
                realized_pnl REAL,
                commission REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0,
                net REAL,
                notes TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                source TEXT,
                raw TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL
            )
            """
        )
        _ensure_journal_finalization_schema(cur)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs (ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals (ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts_action ON trades (ts, action)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_equity_curve_ts ON equity_curve (ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_entries_close_ts ON journal_entries (close_ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_entries_source ON journal_entries (source)")
        conn.commit()
    finally:
        conn.close()


def add_log(db_path: str, ts: int, level: str, message: str) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO logs (ts, level, message) VALUES (?, ?, ?)", (ts, level, message))
        _trim_table_by_id(cur, "logs", MAX_LOG_ROWS)
        conn.commit()
    finally:
        conn.close()


def get_logs(db_path: str, limit: int = 100) -> List[Dict[str, Any]]:
    conn = _connect(db_path)
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
    conn = _connect(db_path)
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
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, ts, action, coin, side, margin, leverage, status, notes
            FROM trades ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "ts": row[1],
                "action": row[2],
                "coin": row[3],
                "side": row[4],
                "margin": row[5],
                "leverage": row[6],
                "status": row[7],
                "notes": row[8],
            }
            for row in rows
        ]
    finally:
        conn.close()


def replace_journal_entries(db_path: str, items: List[Dict[str, Any]], now: int) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS temp_journal_ids")
        cur.execute("CREATE TEMP TABLE temp_journal_ids (external_id TEXT PRIMARY KEY)")

        for item in items:
            external_id = str(item.get("external_id", "") or "").strip()
            if not external_id:
                continue
            finalization_state, estimated_source = _derive_finalization_fields(
                item.get("realized_pnl"),
                item.get("exit_price"),
                item.get("raw", "{}"),
            )
            cur.execute("INSERT OR IGNORE INTO temp_journal_ids (external_id) VALUES (?)", (external_id,))
            cur.execute(
                """
                INSERT INTO journal_entries (
                    external_id,
                    close_ts,
                    symbol,
                    side,
                    qty,
                    entry_price,
                    exit_price,
                    realized_pnl,
                    commission,
                    fees,
                    net,
                    source,
                    raw,
                    finalization_state,
                    estimated_source,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET
                    close_ts=excluded.close_ts,
                    symbol=excluded.symbol,
                    side=excluded.side,
                    qty=excluded.qty,
                    entry_price=excluded.entry_price,
                    exit_price=excluded.exit_price,
                    realized_pnl=excluded.realized_pnl,
                    commission=excluded.commission,
                    fees=excluded.fees,
                    net=excluded.net,
                    source=excluded.source,
                    raw=excluded.raw,
                    finalization_state=excluded.finalization_state,
                    estimated_source=excluded.estimated_source,
                    updated_at=excluded.updated_at
                """,
                (
                    external_id,
                    int(item.get("close_ts", 0) or 0),
                    item.get("symbol", ""),
                    item.get("side", ""),
                    item.get("qty"),
                    item.get("entry_price"),
                    item.get("exit_price"),
                    item.get("realized_pnl"),
                    float(item.get("commission", 0) or 0),
                    float(item.get("fees", 0) or 0),
                    item.get("net"),
                    item.get("source", ""),
                    item.get("raw", "{}"),
                    finalization_state,
                    estimated_source,
                    now,
                ),
            )

        cur.execute(
            """
            DELETE FROM journal_entries
            WHERE external_id NOT IN (SELECT external_id FROM temp_journal_ids)
            """
        )
        conn.commit()
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
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO equity_curve (ts, balance, available, locked, unrealized, total_equity)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, balance, available, locked, unrealized, total_equity),
        )
        _trim_table_by_id(cur, "equity_curve", MAX_EQUITY_ROWS)
        conn.commit()
    finally:
        conn.close()


def get_equity_curve(db_path: str, limit: int = 500) -> List[Dict[str, Any]]:
    conn = _connect(db_path)
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
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO signals (ts, coin, timeframe, signal, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts, coin, timeframe, 1 if signal else 0, details),
        )
        _trim_table_by_id(cur, "signals", MAX_SIGNAL_ROWS)
        conn.commit()
    finally:
        conn.close()


def get_signals(db_path: str, limit: int = 200) -> List[Dict[str, Any]]:
    conn = _connect(db_path)
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
    conn = _connect(db_path)
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
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM kv WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def get_all_kv(db_path: str) -> Dict[str, str]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM kv")
        rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()


def upsert_journal_entries(db_path: str, items: List[Dict[str, Any]], now: int) -> None:
    if not items:
        return
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        for item in items:
            finalization_state, estimated_source = _derive_finalization_fields(
                item.get("realized_pnl"),
                item.get("exit_price"),
                item.get("raw", "{}"),
            )
            cur.execute(
                """
                INSERT INTO journal_entries (
                    external_id,
                    close_ts,
                    symbol,
                    side,
                    qty,
                    entry_price,
                    exit_price,
                    realized_pnl,
                    commission,
                    fees,
                    net,
                    source,
                    raw,
                    finalization_state,
                    estimated_source,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET
                    close_ts=excluded.close_ts,
                    symbol=excluded.symbol,
                    side=excluded.side,
                    qty=excluded.qty,
                    entry_price=excluded.entry_price,
                    exit_price=excluded.exit_price,
                    realized_pnl=excluded.realized_pnl,
                    commission=excluded.commission,
                    fees=excluded.fees,
                    net=excluded.net,
                    source=excluded.source,
                    raw=excluded.raw,
                    finalization_state=excluded.finalization_state,
                    estimated_source=excluded.estimated_source,
                    updated_at=excluded.updated_at
                """,
                (
                    item.get("external_id", ""),
                    int(item.get("close_ts", 0) or 0),
                    item.get("symbol", ""),
                    item.get("side", ""),
                    item.get("qty"),
                    item.get("entry_price"),
                    item.get("exit_price"),
                    item.get("realized_pnl"),
                    float(item.get("commission", 0) or 0),
                    float(item.get("fees", 0) or 0),
                    item.get("net"),
                    item.get("source", ""),
                    item.get("raw", "{}"),
                    finalization_state,
                    estimated_source,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def count_journal_entries(db_path: str, search: str = "") -> int:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        if search:
            like = f"%{search}%"
            cur.execute(
                """
                SELECT COUNT(*) FROM journal_entries
                WHERE symbol LIKE ? OR notes LIKE ? OR tags LIKE ?
                """,
                (like, like, like),
            )
        else:
            cur.execute("SELECT COUNT(*) FROM journal_entries")
        row = cur.fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def get_journal_entries(db_path: str, limit: int = 100, offset: int = 0, search: str = "") -> List[Dict[str, Any]]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        safe_limit = max(1, min(int(limit), 10000))
        safe_offset = max(0, int(offset))
        if search:
            like = f"%{search}%"
            cur.execute(
                """
                SELECT id, external_id, close_ts, symbol, side, qty, entry_price, exit_price,
                       realized_pnl, commission, fees, net, notes, tags, source, raw,
                       finalization_state, estimated_source
                FROM journal_entries
                WHERE symbol LIKE ? OR notes LIKE ? OR tags LIKE ?
                ORDER BY close_ts DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (like, like, like, safe_limit, safe_offset),
            )
        else:
            cur.execute(
                """
                SELECT id, external_id, close_ts, symbol, side, qty, entry_price, exit_price,
                       realized_pnl, commission, fees, net, notes, tags, source, raw,
                       finalization_state, estimated_source
                FROM journal_entries
                ORDER BY close_ts DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, safe_offset),
            )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "external_id": row[1],
                "close_ts": row[2],
                "symbol": row[3],
                "side": row[4],
                "qty": row[5],
                "entry_price": row[6],
                "exit_price": row[7],
                "realized_pnl": row[8],
                "commission": row[9],
                "fees": row[10],
                "net": row[11],
                "notes": row[12],
                "tags": row[13],
                "source": row[14],
                "raw": row[15],
                "finalization_state": row[16],
                "estimated_source": row[17],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_journal_summary(db_path: str, search: str = "") -> Dict[str, Any]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        where = ""
        params: List[Any] = []
        if search:
            where = " WHERE symbol LIKE ? OR notes LIKE ? OR tags LIKE ?"
            like = f"%{search}%"
            params = [like, like, like]
        cur.execute(
            f"""
            SELECT
                COUNT(*),
                COALESCE(SUM(COALESCE(entry_price, 0) * COALESCE(qty, 0)), 0),
                COALESCE(SUM(COALESCE(realized_pnl, 0)), 0),
                COALESCE(SUM(COALESCE(commission, 0)), 0),
                COALESCE(SUM(COALESCE(fees, 0)), 0),
                COALESCE(SUM(COALESCE(net, COALESCE(realized_pnl, 0) - COALESCE(commission, 0) - COALESCE(fees, 0))), 0),
                MAX(COALESCE(net, COALESCE(realized_pnl, 0) - COALESCE(commission, 0) - COALESCE(fees, 0))),
                MIN(COALESCE(net, COALESCE(realized_pnl, 0) - COALESCE(commission, 0) - COALESCE(fees, 0))),
                COALESCE(SUM(CASE WHEN COALESCE(net, COALESCE(realized_pnl, 0) - COALESCE(commission, 0) - COALESCE(fees, 0)) > 0 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN COALESCE(net, COALESCE(realized_pnl, 0) - COALESCE(commission, 0) - COALESCE(fees, 0)) < 0 THEN 1 ELSE 0 END), 0)
            FROM journal_entries{where}
            """,
            tuple(params),
        )
        row = cur.fetchone() or (0, 0, 0, 0, 0, 0, None, None, 0, 0)
        return {
            "fills": int(row[0] or 0),
            "qty": float(row[1] or 0),
            "size_boks": float(row[1] or 0),
            "gross": float(row[2] or 0),
            "commission": float(row[3] or 0),
            "fees": float(row[4] or 0),
            "net": float(row[5] or 0),
            "best": float(row[6] or 0),
            "worst": float(row[7] or 0),
            "wins": int(row[8] or 0),
            "losses": int(row[9] or 0),
        }
    finally:
        conn.close()


def update_journal_entry_annotations(db_path: str, entry_id: int, notes: str, tags: str) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE journal_entries
            SET notes = ?, tags = ?, updated_at = strftime('%s', 'now')
            WHERE id = ?
            """,
            (notes, tags, int(entry_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
