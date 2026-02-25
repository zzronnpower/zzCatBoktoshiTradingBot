#!/usr/bin/env python3
import argparse
import json
import sqlite3
import time
from typing import Any, Dict, List


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_rows(db_path: str, limit: int = 10000) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT external_id, close_ts, symbol, side, qty, entry_price, exit_price,
                   realized_pnl, source, notes, raw
            FROM journal_entries
            ORDER BY close_ts DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 100000)),),
        )
        rows = cur.fetchall()
        return [
            {
                "external_id": r[0],
                "close_ts": r[1],
                "symbol": r[2],
                "side": r[3],
                "qty": r[4],
                "entry_price": r[5],
                "exit_price": r[6],
                "realized_pnl": r[7],
                "source": r[8],
                "notes": r[9],
                "raw": r[10],
            }
            for r in rows
        ]
    finally:
        conn.close()


def build_report(rows: List[Dict[str, Any]], stale_sec: int = 3600) -> Dict[str, Any]:
    now = int(time.time())
    ext_count: Dict[str, int] = {}
    stale_pending: List[Dict[str, Any]] = []
    missing_core: List[Dict[str, Any]] = []

    for row in rows:
        ext = str(row.get("external_id", "") or "")
        if ext:
            ext_count[ext] = ext_count.get(ext, 0) + 1

        realized = row.get("realized_pnl")
        recovered = ext.startswith("recovered:")
        try:
            raw_obj = json.loads(str(row.get("raw", "") or "{}"))
            if isinstance(raw_obj, dict) and str(raw_obj.get("origin", "")).lower().startswith("recovered"):
                recovered = True
        except Exception:
            pass
        close_ts = int(row.get("close_ts", 0) or 0)
        if (not recovered) and realized in (None, "") and close_ts > 0 and (now - close_ts) > stale_sec:
            stale_pending.append(
                {
                    "external_id": ext,
                    "symbol": row.get("symbol"),
                    "age_sec": now - close_ts,
                }
            )

        entry_missing = row.get("entry_price") in (None, "")
        size_missing = (row.get("qty") in (None, "")) and (_to_float(row.get("entry_price"), 0) <= 0)
        source_missing = str(row.get("source", "") or "").strip() in {"", "unknown"}
        if entry_missing or size_missing or source_missing:
            missing_core.append(
                {
                    "external_id": ext,
                    "symbol": row.get("symbol"),
                    "entry_missing": bool(entry_missing),
                    "size_missing": bool(size_missing),
                    "source_missing": bool(source_missing),
                }
            )

    duplicates = [k for k, v in ext_count.items() if v > 1]
    return {
        "checked_at": now,
        "total_rows": len(rows),
        "duplicate_external_id_count": len(duplicates),
        "duplicate_external_ids": duplicates[:100],
        "stale_pending_count": len(stale_pending),
        "stale_pending_examples": stale_pending[:100],
        "missing_core_fields_count": len(missing_core),
        "missing_core_examples": missing_core[:100],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run journal integrity checks")
    parser.add_argument("--db", default="/app/data/bot.db", help="Path to sqlite database")
    parser.add_argument("--limit", type=int, default=10000, help="Max journal rows to scan")
    parser.add_argument("--stale-sec", type=int, default=3600, help="Pending age threshold in seconds")
    args = parser.parse_args()

    rows = load_rows(args.db, args.limit)
    report = build_report(rows, args.stale_sec)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
