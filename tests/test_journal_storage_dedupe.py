from app.storage import get_journal_entries, init_db, replace_journal_entries


def _item(external_id: str, close_ts: int, symbol: str = "ETH", realized=None):
    return {
        "external_id": external_id,
        "close_ts": close_ts,
        "symbol": symbol,
        "side": "LONG",
        "qty": 1.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl": realized,
        "commission": 0.0,
        "fees": 0.0,
        "net": realized,
        "source": "manual",
        "raw": "{}",
    }


def test_replace_journal_entries_deduplicates_and_prunes(tmp_path):
    db_path = str(tmp_path / "bot.db")
    init_db(db_path)

    first = [_item("a", 100, realized=1.0), _item("b", 200, realized=2.0)]
    replace_journal_entries(db_path, first, now=1000)

    rows = get_journal_entries(db_path, limit=10, offset=0)
    assert len(rows) == 2
    assert {r["external_id"] for r in rows} == {"a", "b"}

    second = [_item("a", 300, realized=3.5), _item("c", 250, symbol="DOGE", realized=-1.0)]
    replace_journal_entries(db_path, second, now=2000)

    rows2 = get_journal_entries(db_path, limit=10, offset=0)
    assert len(rows2) == 2
    assert {r["external_id"] for r in rows2} == {"a", "c"}

    row_a = next(r for r in rows2 if r["external_id"] == "a")
    assert row_a["close_ts"] == 300
    assert row_a["realized_pnl"] == 3.5
    assert row_a["finalization_state"] == "FINALIZED"
    assert row_a["estimated_source"] == "none"
