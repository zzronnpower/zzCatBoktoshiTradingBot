import json

import BoktoshiBotModule.bot_runner as bot_runner_module
from BoktoshiBotModule.bot_runner import BotRunner
from app.storage import get_kv, init_db, set_kv


def make_runner(tmp_path):
    db_path = str(tmp_path / "bot.db")
    init_db(db_path)
    runner = BotRunner(
        db_path=db_path,
        base_url="https://example.com/api/v1",
        api_key="test_key",
        poll_seconds=20,
        dry_run=False,
        bot_name="test",
        bot_desc="test",
        trade_coin="ETHUSDT",
        margin_boks=100.0,
        leverage=5.0,
        sl_capital_pct=0.01,
        tp_capital_pct=0.03,
        max_positions=5,
    )
    return runner


def test_sync_owned_position_ids_clears_stale(tmp_path):
    runner = make_runner(tmp_path)
    set_kv(runner.db_path, "strategy_position_id", "s1")
    set_kv(runner.db_path, "manual_position_ids", json.dumps(["m1", "m2"]))

    positions = [
        {"positionId": "m1", "coin": "ETH", "side": "LONG", "openedAt": 1000},
        {"positionId": "u1", "coin": "ETH", "side": "LONG", "openedAt": 1001},
    ]
    runner._sync_owned_position_ids(1700000000, positions)

    assert get_kv(runner.db_path, "strategy_position_id", "") == ""
    assert runner._get_manual_position_ids() == ["m1"]


def test_pause_resume_updates_status_kv(tmp_path):
    runner = make_runner(tmp_path)

    pause_result = runner.pause_strategy()
    assert pause_result["success"] is True
    assert pause_result["paused"] is True
    assert get_kv(runner.db_path, "bot_status", "") == "paused"
    assert get_kv(runner.db_path, "strategy_state", "") == "paused"

    resume_result = runner.resume_strategy()
    assert resume_result["success"] is True
    assert resume_result["paused"] is False
    assert get_kv(runner.db_path, "bot_status", "") == "running"
    assert get_kv(runner.db_path, "strategy_state", "") == "running"


def test_manual_close_rejects_strategy_and_closes_selected_manual(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    set_kv(runner.db_path, "strategy_position_id", "s1")
    set_kv(runner.db_path, "manual_position_ids", json.dumps(["m1", "m2"]))

    positions = [
        {"positionId": "s1", "coin": "ETH", "side": "LONG", "openedAt": 1000},
        {"positionId": "m1", "coin": "ETH", "side": "LONG", "openedAt": 1001},
        {"positionId": "m2", "coin": "BTC", "side": "LONG", "openedAt": 1002},
    ]

    monkeypatch.setattr(runner, "_fetch_positions", lambda now: positions)
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, pos: None)
    monkeypatch.setattr(runner, "_can_send_trade", lambda now: True)
    monkeypatch.setattr(runner.client, "close_trade", lambda payload: {"ok": True, "payload": payload})

    reject = runner.manual_close_eth_positions(position_id="s1")
    assert reject["success"] is False
    assert "manual-owned" in reject["message"]

    closed = runner.manual_close_eth_positions(position_id="m1")
    assert closed["success"] is True
    assert closed["closed"] == 1
    assert runner._get_manual_position_ids() == ["m2"]


def test_ema_strategy_trailing_stop_after_1r(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.active_strategy = runner.STRATEGY_EMA_RSI
    set_kv(runner.db_path, "strategy_position_id", "s1")

    closes = [100 + i for i in range(80)]
    candles = [{"open_time": i * 900000, "close": c} for i, c in enumerate(closes)]
    monkeypatch.setattr(runner, "_get_closed_ema_candles", lambda: candles)

    close_calls = []
    monkeypatch.setattr(
        runner,
        "_close_position",
        lambda now, position_id, note, comment="", owner="": close_calls.append(
            {"position_id": position_id, "note": note, "comment": comment, "owner": owner}
        ),
    )

    account = {"boks": {"balance": 1000, "lockedMargin": 0}}
    pos_high = [{"positionId": "s1", "coin": "ETH", "side": "LONG", "unrealizedPnl": 12.0}]
    runner._manage_open_positions(1700000000, account, pos_high)

    state = runner._get_ema_state()
    assert state.get("trailing_active") is True
    assert state.get("peak_pnl", 0) >= 12.0
    assert close_calls == []

    pos_drawdown = [{"positionId": "s1", "coin": "ETH", "side": "LONG", "unrealizedPnl": 1.0}]
    runner._manage_open_positions(1700000010, account, pos_drawdown)
    assert len(close_calls) == 1
    assert "trailing stop" in close_calls[0]["comment"].lower()


def test_ema_strategy_cross_down_exits_position(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.active_strategy = runner.STRATEGY_EMA_RSI
    set_kv(runner.db_path, "strategy_position_id", "s1")

    monkeypatch.setattr(bot_runner_module, "evaluate_exit_ema_cross_down_15m", lambda candles: {"signal": True})
    monkeypatch.setattr(runner, "_get_closed_ema_candles", lambda: [{"open_time": 1, "close": 100.0}] * 80)

    close_calls = []
    monkeypatch.setattr(
        runner,
        "_close_position",
        lambda now, position_id, note, comment="", owner="": close_calls.append(
            {"position_id": position_id, "note": note, "comment": comment, "owner": owner}
        ),
    )

    account = {"boks": {"balance": 1000, "lockedMargin": 0}}
    positions = [{"positionId": "s1", "coin": "ETH", "side": "LONG", "unrealizedPnl": 4.0}]
    runner._manage_open_positions(1700000020, account, positions)

    assert len(close_calls) == 1
    assert "cross down" in close_calls[0]["comment"].lower()


def test_ema_strategy_keeps_one_position_per_symbol(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.active_strategy = runner.STRATEGY_EMA_RSI

    open_called = {"value": False}
    monkeypatch.setattr(runner.client, "open_trade", lambda payload: open_called.__setitem__("value", True) or {"ok": True})

    account = {"boks": {"balance": 1000, "lockedMargin": 0}}
    positions = [{"positionId": "m1", "coin": "ETH", "side": "LONG", "openedAt": 1000}]
    runner._maybe_open_long(1700000030, account, positions)

    assert open_called["value"] is False
