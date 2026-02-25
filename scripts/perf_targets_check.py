#!/usr/bin/env python3
import argparse
import json
import statistics
import time
from typing import Dict, List

import requests


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int(round((p / 100.0) * (len(sorted_values) - 1)))
    return float(sorted_values[max(0, min(idx, len(sorted_values) - 1))])


def benchmark(base_url: str, path: str, runs: int, timeout: float) -> Dict[str, float]:
    latencies: List[float] = []
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        resp = requests.get(f"{base_url}{path}", timeout=timeout)
        resp.raise_for_status()
        latencies.append((time.perf_counter() - t0) * 1000)
    return {
        "count": float(len(latencies)),
        "avg_ms": float(statistics.fmean(latencies) if latencies else 0.0),
        "p95_ms": percentile(latencies, 95),
        "max_ms": float(max(latencies) if latencies else 0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check API latency against target thresholds")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--runs", type=int, default=12, help="Runs per endpoint")
    parser.add_argument("--timeout", type=float, default=20.0, help="Request timeout seconds")
    args = parser.parse_args()

    targets = {
        "/api/trade-history": 40.0,
        "/api/journal?page=1&page_size=20": 25.0,
    }

    report: Dict[str, Dict[str, float]] = {}
    failed = False

    # warm-up
    requests.get(f"{args.base_url}/api/status", timeout=args.timeout)
    requests.get(f"{args.base_url}/api/trade-history", timeout=args.timeout)

    for path, target_p95 in targets.items():
        stats = benchmark(args.base_url, path, runs=args.runs, timeout=args.timeout)
        stats["target_p95_ms"] = float(target_p95)
        stats["pass"] = 1.0 if stats["p95_ms"] <= target_p95 else 0.0
        if stats["pass"] < 1:
            failed = True
        report[path] = stats

    # force refresh target
    t0 = time.perf_counter()
    resp = requests.post(f"{args.base_url}/api/journal/refresh", timeout=args.timeout)
    resp.raise_for_status()
    refresh_ms = (time.perf_counter() - t0) * 1000
    report["/api/journal/refresh"] = {
        "count": 1.0,
        "avg_ms": refresh_ms,
        "p95_ms": refresh_ms,
        "max_ms": refresh_ms,
        "target_p95_ms": 5000.0,
        "pass": 1.0 if refresh_ms <= 5000.0 else 0.0,
    }
    if refresh_ms > 5000.0:
        failed = True

    print(json.dumps(report, ensure_ascii=True, indent=2))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
