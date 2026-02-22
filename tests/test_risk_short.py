from BoktoshiBotModule.risk import build_long_sl_tp_prices, build_short_sl_tp_prices


def test_short_targets_are_inverse_of_long_directionally():
    entry = 2000.0
    capital = 1000.0
    margin = 100.0
    leverage = 5.0
    sl_pct = 0.01
    tp_pct = 0.03

    long_targets = build_long_sl_tp_prices(entry, capital, margin, leverage, sl_pct, tp_pct)
    short_targets = build_short_sl_tp_prices(entry, capital, margin, leverage, sl_pct, tp_pct)

    assert long_targets["stop_loss"] < entry
    assert long_targets["take_profit"] > entry
    assert short_targets["stop_loss"] > entry
    assert short_targets["take_profit"] < entry
