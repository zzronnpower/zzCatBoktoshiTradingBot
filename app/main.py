import json
import os
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .aster_client import AsterClient
from .bot_runner import BotRunner
from AsterTradingModule import AsterManualTradingService, AsterTradingConfig
from .storage import (
    get_all_kv,
    get_equity_curve,
    get_logs,
    get_signals,
    get_trades,
    init_db,
)


def _load_env_file_if_exists(path: str) -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if value and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except Exception:
        return


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


_load_env_file_if_exists("BoktoshiBotModule/.env")
_load_env_file_if_exists("AsterTradingModule/.env")


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
aster_trading = AsterManualTradingService(AsterTradingConfig())

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
    runner.load_runtime_settings_from_db()
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


@app.get("/aster-trading", response_class=HTMLResponse)
def aster_trading_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("aster_trading.html", {"request": request})


@app.get("/eth-chart", response_class=HTMLResponse)
def eth_chart_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("eth_chart.html", {"request": request})


@app.get("/aster-chart", response_class=HTMLResponse)
def aster_chart_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("eth_chart.html", {"request": request})


@app.get("/api/status")
def status() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    runtime_settings = runner.get_runtime_settings()
    active_strategy = runner.get_active_strategy()
    strategy_map = {item["id"]: item for item in runner.list_strategies()}
    strategy_info = strategy_map.get(active_strategy, strategy_map.get(runner.STRATEGY_MA50, {}))
    return {
        "bot_status": kv.get("bot_status", "unknown"),
        "strategy_state": "paused" if runner.is_strategy_paused() else "running",
        "last_tick": kv.get("last_tick", ""),
        "account_ok": kv.get("account_ok", ""),
        "dry_run": DRY_RUN,
        "trade_pair": TRADE_COIN,
        "trade_coin": runner.trade_coin,
        "strategy": {
            "id": active_strategy,
            "name": strategy_info.get("label", active_strategy),
            "entry": strategy_info.get("entry", ""),
            "short_enabled": False,
            "margin_boks": runtime_settings["margin_boks"],
            "leverage": runtime_settings["leverage"],
            "sl_capital_pct": runtime_settings["sl_capital_pct"],
            "tp_capital_pct": runtime_settings["tp_capital_pct"],
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
        "manual_positions": grouped.get("manual_positions", []),
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


@app.get("/api/bot/settings")
def bot_settings() -> Dict[str, Any]:
    values = runner.get_runtime_settings()
    return {
        "margin_boks": values["margin_boks"],
        "leverage": values["leverage"],
        "sl_capital_pct": values["sl_capital_pct"],
        "tp_capital_pct": values["tp_capital_pct"],
        "sl_percent": values["sl_capital_pct"] * 100,
        "tp_percent": values["tp_capital_pct"] * 100,
    }


@app.post("/api/bot/settings")
def update_bot_settings(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    parsed = {
        "margin_boks": payload.get("margin_boks"),
        "leverage": payload.get("leverage"),
        "sl_capital_pct": payload.get("sl_capital_pct"),
        "tp_capital_pct": payload.get("tp_capital_pct"),
    }

    sl_percent = payload.get("sl_percent")
    tp_percent = payload.get("tp_percent")
    if sl_percent is not None:
        try:
            parsed["sl_capital_pct"] = float(sl_percent) / 100
        except Exception:
            pass
    if tp_percent is not None:
        try:
            parsed["tp_capital_pct"] = float(tp_percent) / 100
        except Exception:
            pass

    updated = runner.apply_runtime_settings(parsed)
    return {
        "success": True,
        "settings": {
            "margin_boks": updated["margin_boks"],
            "leverage": updated["leverage"],
            "sl_capital_pct": updated["sl_capital_pct"],
            "tp_capital_pct": updated["tp_capital_pct"],
            "sl_percent": updated["sl_capital_pct"] * 100,
            "tp_percent": updated["tp_capital_pct"] * 100,
        },
    }


@app.get("/api/strategies")
def list_strategies() -> Dict[str, Any]:
    return {"active": runner.get_active_strategy(), "items": runner.list_strategies()}


@app.post("/api/strategy/select")
def select_strategy(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    strategy_id = str(payload.get("strategy_id", "") or "")
    result = runner.set_active_strategy(strategy_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=str(result.get("message", "Invalid strategy")))
    return {
        "success": True,
        "active": runner.get_active_strategy(),
        "items": runner.list_strategies(),
    }


@app.post("/api/manual/force-open-long")
def manual_force_open_long(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    symbol = str(payload.get("symbol", "ETHUSDT") or "ETHUSDT").upper()
    return runner.manual_force_open_long(symbol=symbol, comment="Manual open LONG position from dashboard")


@app.post("/api/manual/close-position")
def manual_close_position(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    position_id = str(payload.get("position_id", "") or "")
    return runner.manual_close_eth_positions(position_id=position_id, comment="Manual close LONG position from dashboard")


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


@app.get("/api/aster/symbols")
def aster_symbols() -> Dict[str, Any]:
    try:
        items = aster.get_usdt_symbols_ranked(
            pinned_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "HYPEUSDT", "PUMPUSDT", "DOGEUSDT"]
        )
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/account-overview")
def aster_trading_account_overview() -> Dict[str, Any]:
    try:
        return aster_trading.get_account_overview()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/aster-trading/order-preview")
def aster_trading_order_preview(payload: Dict[str, Any] = Body(default={})):  # type: ignore[valid-type]
    try:
        return aster_trading.preview_order(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/aster-trading/place-order")
def aster_trading_place_order(payload: Dict[str, Any] = Body(default={})):  # type: ignore[valid-type]
    try:
        return aster_trading.place_manual_order(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/aster-trading/close-position")
def aster_trading_close_position(payload: Dict[str, Any] = Body(default={})):  # type: ignore[valid-type]
    try:
        return aster_trading.close_position_market(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/aster-trading/open-positions")
def aster_trading_open_positions() -> Dict[str, Any]:
    try:
        return aster_trading.get_open_positions()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/open-orders")
def aster_trading_open_orders() -> Dict[str, Any]:
    try:
        return aster_trading.get_open_orders()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/trade-history")
def aster_trading_trade_history(limit: int = 100) -> Dict[str, Any]:
    try:
        return aster_trading.get_trade_history(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/pnl-history")
def aster_trading_pnl_history(limit: int = 100) -> Dict[str, Any]:
    try:
        return aster_trading.get_income_history(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
