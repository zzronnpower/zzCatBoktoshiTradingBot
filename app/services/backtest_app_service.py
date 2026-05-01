import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DATA_DIR = Path(os.getenv("BACKTEST_DATA_DIR", str(PROJECT_ROOT / "BacktestModule" / "artifacts")))
LATEST_BACKTEST_FILE = BACKTEST_DATA_DIR / "latest.json"
RUNS_DIR = BACKTEST_DATA_DIR / "runs"
FREQTRADE_PROJECT_DIR = Path(
    os.getenv(
        "FREQTRADE_PROJECT_DIR",
        "/freqtrade_host" if Path("/freqtrade_host").exists() else str(PROJECT_ROOT.parent / "FreqTradeProject" / "freqtrade"),
    )
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _pick_strategy(result: Dict[str, Any], strategy_name: str = "") -> str:
    strategy_map = result.get("strategy")
    if not isinstance(strategy_map, dict) or not strategy_map:
        raise ValueError("Invalid Freqtrade result: missing strategy payload")

    if strategy_name and strategy_name in strategy_map:
        return strategy_name

    names = list(strategy_map.keys())
    return str(names[0])


def _build_curves(trades: List[Dict[str, Any]], starting_balance: float) -> Dict[str, Any]:
    sorted_trades = sorted(trades, key=lambda t: _safe_float(t.get("close_timestamp", 0.0), 0.0))
    equity_curve: List[Dict[str, Any]] = []
    drawdown_curve: List[Dict[str, Any]] = []

    balance = float(starting_balance)
    peak_balance = float(starting_balance)

    for trade in sorted_trades:
        close_ts_ms = _safe_float(trade.get("close_timestamp", 0.0), 0.0)
        close_ts_sec = int(close_ts_ms / 1000) if close_ts_ms > 1e12 else int(close_ts_ms)
        profit_abs = _safe_float(trade.get("profit_abs", 0.0), 0.0)
        balance += profit_abs
        if balance > peak_balance:
            peak_balance = balance
        drawdown_pct = 0.0
        if peak_balance > 0:
            drawdown_pct = (balance - peak_balance) / peak_balance

        equity_curve.append({"time": close_ts_sec, "value": round(balance, 8)})
        drawdown_curve.append({"time": close_ts_sec, "value": round(drawdown_pct * 100.0, 6)})

    final_balance = balance
    total_pnl_abs = final_balance - starting_balance
    total_pnl_pct = (total_pnl_abs / starting_balance) if starting_balance > 0 else 0.0

    return {
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "final_balance": final_balance,
        "total_pnl_abs": total_pnl_abs,
        "total_pnl_pct": total_pnl_pct,
    }


def _summarize_trades(strategy_data: Dict[str, Any], trades: List[Dict[str, Any]], starting_balance: float) -> Dict[str, Any]:
    curves = _build_curves(trades, starting_balance)
    wins = _safe_int(strategy_data.get("wins", 0), 0)
    losses = _safe_int(strategy_data.get("losses", 0), 0)
    draws = _safe_int(strategy_data.get("draws", 0), 0)
    total = len(trades)

    if wins == 0 and losses == 0 and draws == 0:
        for trade in trades:
            profit = _safe_float(trade.get("profit_abs", 0.0), 0.0)
            if profit > 0:
                wins += 1
            elif profit < 0:
                losses += 1
            else:
                draws += 1

    win_rate = (wins / total) if total > 0 else 0.0
    gross_profit = sum(_safe_float(t.get("profit_abs", 0.0), 0.0) for t in trades if _safe_float(t.get("profit_abs", 0.0), 0.0) > 0)
    gross_loss = abs(sum(_safe_float(t.get("profit_abs", 0.0), 0.0) for t in trades if _safe_float(t.get("profit_abs", 0.0), 0.0) < 0))
    profit_factor = _safe_float(strategy_data.get("profit_factor", 0.0), 0.0)
    if profit_factor <= 0 and gross_loss > 0:
        profit_factor = gross_profit / gross_loss

    max_drawdown_pct = abs(_safe_float(strategy_data.get("max_drawdown_account", 0.0), 0.0)) * 100.0
    max_drawdown_abs = _safe_float(strategy_data.get("max_drawdown_abs", 0.0), 0.0)

    normalized_recent = []
    for trade in sorted(trades, key=lambda t: _safe_float(t.get("close_timestamp", 0.0), 0.0), reverse=True)[:20]:
        open_ts_ms = _safe_float(trade.get("open_timestamp", 0.0), 0.0)
        close_ts_ms = _safe_float(trade.get("close_timestamp", 0.0), 0.0)
        open_ts = int(open_ts_ms / 1000) if open_ts_ms > 1e12 else int(open_ts_ms)
        close_ts = int(close_ts_ms / 1000) if close_ts_ms > 1e12 else int(close_ts_ms)
        normalized_recent.append(
            {
                "pair": str(trade.get("pair", "")),
                "is_short": bool(trade.get("is_short", False)),
                "open_time": open_ts,
                "close_time": close_ts,
                "duration_min": _safe_int(trade.get("trade_duration", 0), 0),
                "open_rate": _safe_float(trade.get("open_rate", 0.0), 0.0),
                "close_rate": _safe_float(trade.get("close_rate", 0.0), 0.0),
                "profit_abs": _safe_float(trade.get("profit_abs", 0.0), 0.0),
                "profit_pct": _safe_float(trade.get("profit_ratio", 0.0), 0.0) * 100.0,
                "exit_reason": str(trade.get("exit_reason", "")),
            }
        )

    summary = {
        "starting_balance": float(starting_balance),
        "final_balance": float(curves["final_balance"]),
        "total_pnl_abs": float(curves["total_pnl_abs"]),
        "total_pnl_pct": float(curves["total_pnl_pct"] * 100.0),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate_pct": win_rate * 100.0,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown_pct,
        "max_drawdown_abs": max_drawdown_abs,
    }

    return {
        "summary": summary,
        "equity_curve": curves["equity_curve"],
        "drawdown_curve": curves["drawdown_curve"],
        "recent_trades": normalized_recent,
    }


def build_artifact_from_freqtrade_result(
    *,
    freqtrade_result_path: str,
    strategy_name: str = "",
    pair_filter: Optional[str] = "SOL/USDT:USDT",
) -> Dict[str, Any]:
    result_file = Path(freqtrade_result_path)
    if not result_file.exists():
        raise FileNotFoundError(f"Freqtrade result file not found: {result_file}")

    payload: Dict[str, Any]
    if result_file.suffix.lower() == ".zip":
        with ZipFile(result_file, "r") as archive:
            json_members = [name for name in archive.namelist() if name.lower().endswith(".json") and "_config" not in name.lower()]
            if not json_members:
                raise ValueError(f"No result JSON found in zip file: {result_file}")
            with archive.open(json_members[0], "r") as member:
                payload = json.loads(member.read().decode("utf-8"))
    else:
        with result_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)

    picked_strategy = _pick_strategy(payload, strategy_name=strategy_name)
    strategy_data = payload.get("strategy", {}).get(picked_strategy, {})
    if not isinstance(strategy_data, dict):
        raise ValueError("Invalid Freqtrade result: malformed strategy section")

    raw_trades = strategy_data.get("trades", [])
    trades: List[Dict[str, Any]] = [trade for trade in raw_trades if isinstance(trade, dict)]
    if pair_filter:
        trades = [t for t in trades if str(t.get("pair", "")).upper() == str(pair_filter).upper()]

    starting_balance = _safe_float(strategy_data.get("starting_balance", 10000.0), 10000.0)
    built = _summarize_trades(strategy_data, trades, starting_balance)

    metadata = payload.get("metadata", {}).get(picked_strategy, {})
    artifact = {
        "generated_at": int(time.time()),
        "source": {
            "file": str(result_file),
            "strategy": picked_strategy,
            "pair_filter": pair_filter or "",
            "run_id": str(metadata.get("run_id", "")),
            "backtest_start_time": str(metadata.get("backtest_start_time", "")),
        },
        "context": {
            "pair": pair_filter or "",
            "timeframe": str(strategy_data.get("timeframe", "")),
            "timerange": str(strategy_data.get("timerange", "")),
            "trading_mode": "futures",
            "exchange": "binance",
        },
        **built,
    }
    return artifact


def write_latest_backtest_artifact(artifact: Dict[str, Any]) -> str:
    BACKTEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    generated_at = _safe_int(artifact.get("generated_at", int(time.time())), int(time.time()))
    run_id = str(artifact.get("source", {}).get("run_id", "") or "").strip()
    source_file = str(artifact.get("source", {}).get("file", "") or "")
    source_stem = Path(source_file).stem if source_file else "run"
    base_id = run_id or f"{generated_at}_{source_stem}".replace(" ", "_")
    artifact_id = base_id
    out_file = RUNS_DIR / f"{artifact_id}.json"
    suffix = 1
    while out_file.exists():
        artifact_id = f"{base_id}_{suffix}"
        out_file = RUNS_DIR / f"{artifact_id}.json"
        suffix += 1

    enriched = dict(artifact)
    enriched["artifact_id"] = artifact_id

    with out_file.open("w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=True)
    with LATEST_BACKTEST_FILE.open("w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=True)
    return str(LATEST_BACKTEST_FILE)


def load_latest_backtest_artifact() -> Dict[str, Any]:
    if not LATEST_BACKTEST_FILE.exists():
        raise FileNotFoundError(
            f"Backtest artifact not found at {LATEST_BACKTEST_FILE}. Generate it first from Freqtrade results."
        )
    with LATEST_BACKTEST_FILE.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Invalid latest backtest artifact")
    return payload


def _load_artifact_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid backtest artifact: {path}")
    return payload


def list_backtest_runs(
    limit: int = 30,
    *,
    timeframe: str = "",
    timerange: str = "",
    strategy: str = "",
    pair: str = "",
    label_query: str = "",
) -> List[Dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    tf_filter = str(timeframe or "").strip().lower()
    tr_filter = str(timerange or "").strip().lower()
    strategy_filter = str(strategy or "").strip().lower()
    pair_filter = str(pair or "").strip().lower()
    label_filter = str(label_query or "").strip().lower()

    for file in files:
        try:
            payload = _load_artifact_file(file)
        except Exception:
            continue
        summary = payload.get("summary", {})
        context = payload.get("context", {})
        source = payload.get("source", {})
        item = {
            "artifact_id": str(payload.get("artifact_id", file.stem)),
            "generated_at": _safe_int(payload.get("generated_at", 0), 0),
            "label": str(payload.get("label", "") or ""),
            "pair": str(context.get("pair", "")),
            "strategy": str(source.get("strategy", "")),
            "timeframe": str(context.get("timeframe", "")),
            "timerange": str(context.get("timerange", "")),
            "total_pnl_abs": _safe_float(summary.get("total_pnl_abs", 0.0), 0.0),
            "total_pnl_pct": _safe_float(summary.get("total_pnl_pct", 0.0), 0.0),
            "profit_factor": _safe_float(summary.get("profit_factor", 0.0), 0.0),
            "win_rate_pct": _safe_float(summary.get("win_rate_pct", 0.0), 0.0),
            "total_trades": _safe_int(summary.get("total_trades", 0), 0),
        }

        item_timeframe = str(item.get("timeframe", "")).lower()
        item_timerange = str(item.get("timerange", "")).lower()
        item_strategy = str(item.get("strategy", "")).lower()
        item_pair = str(item.get("pair", "")).lower()
        item_label = str(item.get("label", "")).lower()
        item_artifact = str(item.get("artifact_id", "")).lower()

        if tf_filter and tf_filter != item_timeframe:
            continue
        if tr_filter and tr_filter not in item_timerange:
            continue
        if strategy_filter and strategy_filter not in item_strategy:
            continue
        if pair_filter and pair_filter not in item_pair:
            continue
        if label_filter and (label_filter not in item_label and label_filter not in item_artifact):
            continue

        out.append(item)
        if len(out) >= max(1, limit):
            break
    return out


def list_backtest_strategies() -> List[str]:
    if not RUNS_DIR.exists():
        return []
    values: set[str] = set()
    for file in RUNS_DIR.glob("*.json"):
        try:
            payload = _load_artifact_file(file)
        except Exception:
            continue
        strategy_name = str(payload.get("source", {}).get("strategy", "") or "").strip()
        if strategy_name:
            values.add(strategy_name)
    return sorted(values)


def list_backtest_pairs() -> List[str]:
    if not RUNS_DIR.exists():
        return []
    values: set[str] = set()
    for file in RUNS_DIR.glob("*.json"):
        try:
            payload = _load_artifact_file(file)
        except Exception:
            continue
        pair_name = str(payload.get("context", {}).get("pair", "") or "").strip()
        if pair_name:
            values.add(pair_name)
    return sorted(values)


def load_backtest_artifact_by_id(artifact_id: str) -> Dict[str, Any]:
    candidate = (artifact_id or "").strip()
    if not candidate:
        raise FileNotFoundError("Missing artifact id")
    if candidate == "latest":
        return load_latest_backtest_artifact()
    target = RUNS_DIR / f"{candidate}.json"
    if not target.exists():
        raise FileNotFoundError(f"Backtest run not found: {candidate}")
    return _load_artifact_file(target)


def _summary_delta(base: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, float]:
    keys = [
        "total_pnl_abs",
        "total_pnl_pct",
        "win_rate_pct",
        "profit_factor",
        "max_drawdown_pct",
        "final_balance",
        "total_trades",
    ]
    out: Dict[str, float] = {}
    for key in keys:
        out[key] = _safe_float(candidate.get(key, 0.0), 0.0) - _safe_float(base.get(key, 0.0), 0.0)
    return out


def compare_backtest_runs(base_id: str, candidate_id: str) -> Dict[str, Any]:
    base = load_backtest_artifact_by_id(base_id)
    candidate = load_backtest_artifact_by_id(candidate_id)
    base_summary = base.get("summary", {}) if isinstance(base.get("summary"), dict) else {}
    candidate_summary = candidate.get("summary", {}) if isinstance(candidate.get("summary"), dict) else {}

    return {
        "base": {
            "artifact_id": str(base.get("artifact_id", base_id)),
            "label": str(base.get("label", "") or ""),
            "summary": base_summary,
            "context": base.get("context", {}),
            "source": base.get("source", {}),
            "equity_curve": base.get("equity_curve", []),
            "drawdown_curve": base.get("drawdown_curve", []),
        },
        "candidate": {
            "artifact_id": str(candidate.get("artifact_id", candidate_id)),
            "label": str(candidate.get("label", "") or ""),
            "summary": candidate_summary,
            "context": candidate.get("context", {}),
            "source": candidate.get("source", {}),
            "equity_curve": candidate.get("equity_curve", []),
            "drawdown_curve": candidate.get("drawdown_curve", []),
            "recent_trades": candidate.get("recent_trades", []),
        },
        "delta": _summary_delta(base_summary, candidate_summary),
    }


def _validate_token(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required field: {name}")
    if not re.match(r"^[A-Za-z0-9_:/.\-]+$", text):
        raise ValueError(f"Invalid value for {name}: {text}")
    return text


def run_freqtrade_backtest_and_publish(
    *,
    strategy: str,
    pair: str,
    timeframe: str,
    timerange: str,
    label: str = "",
    timeout_sec: int = 1200,
) -> Dict[str, Any]:
    strategy_name = _validate_token("strategy", strategy)
    pair_name = _validate_token("pair", pair)
    timeframe_name = _validate_token("timeframe", timeframe)
    timerange_name = _validate_token("timerange", timerange)

    project_dir = FREQTRADE_PROJECT_DIR
    if not project_dir.exists():
        raise FileNotFoundError(f"Freqtrade project directory not found: {project_dir}")

    compose_file = project_dir / "docker-compose.yml"
    if not compose_file.exists():
        raise FileNotFoundError(f"Freqtrade docker compose file not found: {compose_file}")

    base_config = project_dir / "user_data" / "config.boktoshi.sol.json"
    if not base_config.exists():
        raise FileNotFoundError(f"Freqtrade base config not found: {base_config}")

    with base_config.open("r", encoding="utf-8") as f:
        config_payload = json.load(f)

    config_payload["timeframe"] = timeframe_name
    exchange = config_payload.setdefault("exchange", {})
    exchange["pair_whitelist"] = [pair_name]
    config_payload["bot_name"] = f"boktoshi-backtest-{int(time.time())}"

    runtime_config = project_dir / "user_data" / "config.boktoshi.runtime.json"
    with runtime_config.open("w", encoding="utf-8") as f:
        json.dump(config_payload, f, ensure_ascii=True)

    common = ["docker-compose", "run", "--rm", "freqtrade"]
    download_cmd = common + [
        "download-data",
        "--config",
        "/freqtrade/user_data/config.boktoshi.runtime.json",
        "--trading-mode",
        "futures",
        "-t",
        timeframe_name,
        "-p",
        pair_name,
        "--timerange",
        timerange_name,
    ]
    subprocess.run(download_cmd, cwd=str(project_dir), check=True, capture_output=True, text=True, timeout=timeout_sec)

    backtest_cmd = common + [
        "backtesting",
        "--config",
        "/freqtrade/user_data/config.boktoshi.runtime.json",
        "--strategy",
        strategy_name,
        "--strategy-path",
        "/freqtrade/user_data/strategies",
        "--timerange",
        timerange_name,
        "--export",
        "trades",
    ]
    backtest_proc = subprocess.run(
        backtest_cmd,
        cwd=str(project_dir),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )

    results_dir = project_dir / "user_data" / "backtest_results"
    zips = sorted(results_dir.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise FileNotFoundError(f"No backtest result zip found in {results_dir}")
    latest_zip = zips[0]

    artifact = build_artifact_from_freqtrade_result(
        freqtrade_result_path=str(latest_zip),
        strategy_name=strategy_name,
        pair_filter=pair_name,
    )
    if label:
        artifact["label"] = str(label)
    write_latest_backtest_artifact(artifact)

    latest = load_latest_backtest_artifact()
    return {
        "ok": True,
        "artifact_id": latest.get("artifact_id", ""),
        "result_zip": str(latest_zip),
        "stdout_tail": str(backtest_proc.stdout or "")[-1000:],
        "summary": latest.get("summary", {}),
    }
