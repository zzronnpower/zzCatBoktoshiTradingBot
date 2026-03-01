import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from app.storage import init_db


def main() -> int:
    db_arg = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "bot.db")
    db_path = str(Path(db_arg).resolve())
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT finalization_state, estimated_source, COUNT(*)
            FROM journal_entries
            GROUP BY finalization_state, estimated_source
            ORDER BY finalization_state, estimated_source
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    print(f"migration_done db={db_path}")
    for state, source, count in rows:
        print(f"{state}/{source}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
