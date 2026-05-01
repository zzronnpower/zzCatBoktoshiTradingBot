#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backtest_app_service import (
    build_artifact_from_freqtrade_result,
    write_latest_backtest_artifact,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Boktoshi backtest artifact from a Freqtrade result JSON file.")
    parser.add_argument("--source", required=True, help="Absolute path to Freqtrade backtest result JSON")
    parser.add_argument("--strategy", default="", help="Freqtrade strategy name to pick from source JSON")
    parser.add_argument("--pair", default="SOL/USDT:USDT", help="Pair filter (default: SOL/USDT:USDT)")
    parser.add_argument("--label", default="", help="Optional run label (e.g. baseline, candidate-v1)")
    parser.add_argument("--print", action="store_true", dest="print_payload", help="Print artifact JSON to stdout")
    args = parser.parse_args()

    artifact = build_artifact_from_freqtrade_result(
        freqtrade_result_path=args.source,
        strategy_name=args.strategy,
        pair_filter=args.pair,
    )
    if args.label:
        artifact["label"] = str(args.label)
    out = write_latest_backtest_artifact(artifact)
    if args.print_payload:
        print(json.dumps(artifact, indent=2, ensure_ascii=True))
    print(f"artifact_saved={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
