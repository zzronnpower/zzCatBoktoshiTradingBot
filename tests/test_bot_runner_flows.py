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


def test_manual_force_open_short_builds_inverse_risk_targets(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    monkeypatch.setattr(runner, "_fetch_account", lambda now: {"boks": {"balance": 1000, "lockedMargin": 0}})
    monkeypatch.setattr(runner, "_fetch_positions", lambda now: [])
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, positions: None)
    monkeypatch.setattr(runner, "_can_send_trade", lambda now: True)
    monkeypatch.setattr(runner.hyperliquid, "get_candles", lambda coin, interval, bars: [{"close": 2000.0}])
    monkeypatch.setattr(runner, "_capture_manual_position_id", lambda *args, **kwargs: None)

    captured = {}

    def fake_open_trade(payload):
        captured["payload"] = payload
        return {"positionId": "short1"}

    monkeypatch.setattr(runner.client, "open_trade", fake_open_trade)

    result = runner.manual_force_open_short(symbol="ETHUSDT")

    assert result["success"] is True
    assert result["side"] == "SHORT"
    payload = captured["payload"]
    assert payload["side"] == "SHORT"
    assert payload["stopLoss"] > 2000.0
    assert payload["takeProfit"] < 2000.0


def test_manual_force_open_short_rejects_hedge_if_long_exists(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    monkeypatch.setattr(runner, "_fetch_account", lambda now: {"boks": {"balance": 1000, "lockedMargin": 0}})
    monkeypatch.setattr(
        runner,
        "_fetch_positions",
        lambda now: [{"positionId": "s1", "coin": "ETH", "side": "LONG", "openedAt": 1000}],
    )
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, positions: None)

    result = runner.manual_force_open_short(symbol="ETHUSDT")

    assert result["success"] is False
    assert "Hedge is disabled" in result["message"]


def test_manual_force_open_long_rejects_if_manual_short_same_symbol_exists(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner._set_manual_position_ids(["m-short"])

    monkeypatch.setattr(runner, "_fetch_account", lambda now: {"boks": {"balance": 1000, "lockedMargin": 0}})
    monkeypatch.setattr(
        runner,
        "_fetch_positions",
        lambda now: [{"positionId": "m-short", "coin": "ETH", "side": "SHORT", "openedAt": 1000}],
    )
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, positions: None)

    result = runner.manual_force_open_long(symbol="ETHUSDT")

    assert result["success"] is False
    assert "already open" in result["message"]


def test_manual_close_all_positions_closes_only_manual_owned(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    set_kv(runner.db_path, "manual_position_ids", json.dumps(["m1", "m2"]))

    positions = [
        {"positionId": "m1", "coin": "ETH", "side": "LONG", "openedAt": 1001},
        {"positionId": "m2", "coin": "BTC", "side": "SHORT", "openedAt": 1002},
        {"positionId": "x1", "coin": "SOL", "side": "LONG", "openedAt": 1003},
    ]
    close_calls = []

    monkeypatch.setattr(runner, "_fetch_positions", lambda now: positions)
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, pos: None)
    monkeypatch.setattr(runner, "_can_send_trade", lambda now: True)
    monkeypatch.setattr(runner.client, "close_trade", lambda payload: close_calls.append(payload) or {"ok": True})

    result = runner.manual_close_all_positions(comment="close all")

    assert result["success"] is True
    assert result["closed"] == 2
    assert len(close_calls) == 2
    assert {c["positionId"] for c in close_calls} == {"m1", "m2"}
    assert runner._get_manual_position_ids() == []


def test_close_strategy_position_closes_selected_strategy_owned(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner._set_strategy_position_map(
        {
            f"{runner.STRATEGY_MA50}:BTCUSDT": "s-btc",
            f"{runner.STRATEGY_MA50}:ETHUSDT": "s-eth",
            f"{runner.STRATEGY_MA50}:SOLUSDT": "s-sol",
        }
    )

    positions = [
        {"positionId": "s-btc", "coin": "BTC", "side": "LONG", "openedAt": 1001},
        {"positionId": "s-eth", "coin": "ETH", "side": "LONG", "openedAt": 1002},
        {"positionId": "s-sol", "coin": "SOL", "side": "LONG", "openedAt": 1003},
    ]
    close_calls = []

    monkeypatch.setattr(runner, "_fetch_positions", lambda now: positions)
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, pos: None)
    monkeypatch.setattr(runner, "_can_send_trade", lambda now: True)
    monkeypatch.setattr(runner.client, "close_trade", lambda payload: close_calls.append(payload) or {"ok": True})

    result = runner.close_strategy_position(position_id="s-sol", comment="close selected")

    assert result["success"] is True
    assert result["closed"] == 1
    assert len(close_calls) == 1
    assert close_calls[0]["positionId"] == "s-sol"
    strategy_map = runner._get_strategy_position_map()
    assert "s-sol" not in strategy_map.values()
    assert "s-btc" in strategy_map.values()
    assert "s-eth" in strategy_map.values()


def test_close_all_strategy_positions_closes_all_strategy_owned(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner._set_strategy_position_map(
        {
            f"{runner.STRATEGY_MA50}:BTCUSDT": "s-btc",
            f"{runner.STRATEGY_MA50}:ETHUSDT": "s-eth",
            f"{runner.STRATEGY_MA50}:SOLUSDT": "s-sol",
        }
    )

    positions = [
        {"positionId": "s-btc", "coin": "BTC", "side": "LONG", "openedAt": 1001},
        {"positionId": "s-eth", "coin": "ETH", "side": "LONG", "openedAt": 1002},
        {"positionId": "s-sol", "coin": "SOL", "side": "LONG", "openedAt": 1003},
        {"positionId": "x1", "coin": "DOGE", "side": "LONG", "openedAt": 1004},
    ]
    close_calls = []

    monkeypatch.setattr(runner, "_fetch_positions", lambda now: positions)
    monkeypatch.setattr(runner, "_sync_owned_position_ids", lambda now, pos: None)
    monkeypatch.setattr(runner, "_can_send_trade", lambda now: True)
    monkeypatch.setattr(runner.client, "close_trade", lambda payload: close_calls.append(payload) or {"ok": True})

    result = runner.close_all_strategy_positions(comment="close all strategy")

    assert result["success"] is True
    assert result["closed"] == 3
    assert len(close_calls) == 3
    assert {c["positionId"] for c in close_calls} == {"s-btc", "s-eth", "s-sol"}
    assert runner._get_strategy_position_map() == {}
