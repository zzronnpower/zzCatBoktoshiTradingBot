#!/usr/bin/env python3
import argparse
import json
import threading
import time
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from app.storage import get_kv, init_db, set_kv


def worker(db_path: str, worker_id: int, loops: int, out: dict) -> None:
    ok = 0
    err = 0
    for i in range(loops):
        key = f"lock_test_{worker_id}_{i % 8}"
        value = f"{worker_id}:{i}:{time.time()}"
        try:
            set_kv(db_path, key, value)
            _ = get_kv(db_path, key, "")
            ok += 1
        except Exception:
            err += 1
    out[worker_id] = {"ok": ok, "err": err}


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite lock contention smoke check")
    parser.add_argument("--db", default="/tmp/boktoshi_lock_test.db", help="Temporary db path")
    parser.add_argument("--workers", type=int, default=8, help="Number of concurrent workers")
    parser.add_argument("--loops", type=int, default=200, help="Writes per worker")
    args = parser.parse_args()

    db_path = str(Path(args.db).resolve())
    init_db(db_path)

    out = {}
    threads = [threading.Thread(target=worker, args=(db_path, i, max(1, args.loops), out), daemon=True) for i in range(max(1, args.workers))]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duration_ms = (time.perf_counter() - t0) * 1000

    total_ok = sum(v.get("ok", 0) for v in out.values())
    total_err = sum(v.get("err", 0) for v in out.values())
    print(
        json.dumps(
            {
                "db_path": db_path,
                "workers": len(threads),
                "loops": max(1, args.loops),
                "duration_ms": round(duration_ms, 2),
                "total_ok": total_ok,
                "total_err": total_err,
                "error_rate": (total_err / max(1, total_ok + total_err)),
                "workers_detail": out,
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
