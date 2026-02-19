from typing import Dict


def parse_total_capital(account: Dict[str, object]) -> float:
    boks = account.get("boks", {}) if isinstance(account, dict) else {}
    if not isinstance(boks, dict):
        return 0.0
    balance = float(boks.get("balance", 0) or 0)
    locked = float(boks.get("lockedMargin", 0) or 0)
    return max(balance + locked, 0.0)


def build_long_sl_tp_prices(
    entry_price: float,
    capital: float,
    margin: float,
    leverage: float,
    sl_capital_pct: float,
    tp_capital_pct: float,
) -> Dict[str, float]:
    notional = max(margin * leverage, 1e-9)
    sl_pnl_target = -abs(capital * sl_capital_pct)
    tp_pnl_target = abs(capital * tp_capital_pct)

    sl_move_pct = abs(sl_pnl_target) / notional
    tp_move_pct = tp_pnl_target / notional

    stop_loss = max(entry_price * (1 - sl_move_pct), 0.0)
    take_profit = max(entry_price * (1 + tp_move_pct), 0.0)

    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "sl_pnl_target": sl_pnl_target,
        "tp_pnl_target": tp_pnl_target,
        "sl_move_pct": sl_move_pct,
        "tp_move_pct": tp_move_pct,
    }
