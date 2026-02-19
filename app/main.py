import json
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .aster_client import AsterClient
from .bot_runner import BotRunner
from .storage import (
    get_all_kv,
    get_equity_curve,
    get_logs,
    get_signals,
    get_trades,
    init_db,
)


def _env_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_json(value: str) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


DB_PATH = os.getenv("DB_PATH", "/app/data/bot.db")
MTC_API_KEY = os.getenv("MTC_API_KEY", "")
MTC_BASE_URL = os.getenv("MTC_BASE_URL", "https://boktoshi.com/api/v1")
BOT_NAME = os.getenv("BOT_NAME", "zzCatBoktoshiTradingBot")
BOT_DESC = os.getenv("BOT_DESC", "ETHUSDT MA50(4H) long-only bot")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "20"))
DRY_RUN = _env_bool(os.getenv("DRY_RUN", "true"), True)

TRADE_COIN = "ETHUSDT"
MARGIN_BOKS = float(os.getenv("MARGIN_BOKS", "100"))
LEVERAGE = float(os.getenv("LEVERAGE", "5"))
SL_CAPITAL_PCT = float(os.getenv("SL_CAPITAL_PCT", "0.01"))
TP_CAPITAL_PCT = float(os.getenv("TP_CAPITAL_PCT", "0.03"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
ASTER_BASE_URL = os.getenv("ASTER_BASE_URL", "https://www.asterdex.com")

app = FastAPI(title="zzCatBoktoshiTradingBot")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
aster = AsterClient(base_url=ASTER_BASE_URL)

runner = BotRunner(
    db_path=DB_PATH,
    base_url=MTC_BASE_URL,
    api_key=MTC_API_KEY,
    poll_seconds=POLL_SECONDS,
    dry_run=DRY_RUN,
    bot_name=BOT_NAME,
    bot_desc=BOT_DESC,
    trade_coin=TRADE_COIN,
    margin_boks=MARGIN_BOKS,
    leverage=LEVERAGE,
    sl_capital_pct=SL_CAPITAL_PCT,
    tp_capital_pct=TP_CAPITAL_PCT,
    max_positions=MAX_POSITIONS,
)


@app.on_event("startup")
def on_startup() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db(DB_PATH)
    runner.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    runner.stop()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/manual", response_class=HTMLResponse)
def manual_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("manual.html", {"request": request})


@app.get("/chatlog", response_class=HTMLResponse)
def chatlog_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("chatlog.html", {"request": request})


@app.get("/eth-chart", response_class=HTMLResponse)
def eth_chart_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("eth_chart.html", {"request": request})


@app.get("/api/status")
def status() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    return {
        "bot_status": kv.get("bot_status", "unknown"),
        "strategy_state": "paused" if runner.is_strategy_paused() else "running",
        "last_tick": kv.get("last_tick", ""),
        "account_ok": kv.get("account_ok", ""),
        "dry_run": DRY_RUN,
        "trade_pair": TRADE_COIN,
        "trade_coin": runner.trade_coin,
        "strategy": {
            "name": "MA50_4H_CROSSUP_3C_LONG_ONLY",
            "entry": "Price cross above MA50 and closes above MA50 for 3 consecutive 4H candles",
            "short_enabled": False,
            "margin_boks": MARGIN_BOKS,
            "leverage": LEVERAGE,
            "sl_capital_pct": SL_CAPITAL_PCT,
            "tp_capital_pct": TP_CAPITAL_PCT,
        },
        "last_signal": _parse_json(kv.get("last_signal", "")),
    }


@app.get("/api/account")
def account() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    return {"account": _parse_json(kv.get("account", "")), "notices": _parse_json(kv.get("notices", "[]"))}


@app.get("/api/open-positions")
def open_positions() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    positions = _parse_json(kv.get("positions", ""))
    if isinstance(positions, dict):
        items = positions.get("positions", [])
    elif isinstance(positions, list):
        items = positions
    else:
        items = []
    grouped = runner.classify_open_positions(items)
    return {
        "items": items,
        "strategy_position": grouped.get("strategy_position"),
        "manual_position": grouped.get("manual_position"),
        "unknown_positions": grouped.get("unknown_positions", []),
    }


@app.get("/api/trade-history")
def trade_history() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    remote = _parse_json(kv.get("last_history", "[]"))
    if not isinstance(remote, list):
        remote = []
    return {
        "local_exec": get_trades(DB_PATH, limit=300),
        "remote_history": remote,
    }


@app.get("/api/pnl-history")
def pnl_history() -> Dict[str, Any]:
    curve = get_equity_curve(DB_PATH, limit=1000)
    return {"items": curve}


@app.get("/api/signals")
def signals() -> Dict[str, Any]:
    return {"items": get_signals(DB_PATH, limit=200)}


@app.get("/api/logs")
def logs() -> Dict[str, Any]:
    return {"items": get_logs(DB_PATH, limit=300)}


@app.post("/api/manual/force-open-long")
def manual_force_open_long() -> Dict[str, Any]:
    return runner.manual_force_open_long(comment="Manual force open LONG ETHUSDT from dashboard")


@app.post("/api/manual/close-position")
def manual_close_position() -> Dict[str, Any]:
    return runner.manual_close_eth_positions(comment="Manual close LONG ETHUSDT from dashboard")


@app.post("/api/manual/close-strategy-position")
def close_strategy_position() -> Dict[str, Any]:
    return runner.close_strategy_position(comment="Manual close strategy LONG ETHUSDT from dashboard")


@app.post("/api/bot/pause")
def pause_bot_strategy() -> Dict[str, Any]:
    return runner.pause_strategy()


@app.post("/api/bot/resume")
def resume_bot_strategy() -> Dict[str, Any]:
    return runner.resume_strategy()


@app.get("/api/aster/overview")
def aster_overview(symbol: str = "ETHUSDT") -> Dict[str, Any]:
    try:
        return aster.get_overview(symbol=symbol)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster/klines")
def aster_klines(symbol: str = "ETHUSDT", interval: str = "5m", limit: int = 400) -> Dict[str, Any]:
    try:
        return {
            "symbol": symbol,
            "interval": interval,
            "items": aster.get_klines(symbol=symbol, interval=interval, limit=limit),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster/depth")
def aster_depth(symbol: str = "ETHUSDT", limit: int = 20) -> Dict[str, Any]:
    try:
        return aster.get_depth(symbol=symbol, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
