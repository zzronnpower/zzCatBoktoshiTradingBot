from scripts.integrity_check import build_report


def test_integrity_script_ignores_recovered_rows_for_stale_pending():
    now = 2_000_000
    rows = [
        {
            "external_id": "recovered:abc",
            "close_ts": now - 8000,
            "symbol": "PUMP",
            "realized_pnl": None,
            "qty": 1,
            "entry_price": 1,
            "source": "manual",
            "raw": '{"origin":"recovered_from_stale"}',
        },
        {
            "external_id": "local-close:abc",
            "close_ts": now - 8000,
            "symbol": "ETH",
            "realized_pnl": None,
            "qty": 1,
            "entry_price": 1,
            "source": "manual",
            "raw": "{}",
        },
    ]

    report = build_report(rows, stale_sec=3600)

    assert report["stale_pending_count"] == 1
    assert report["stale_pending_examples"][0]["external_id"] == "local-close:abc"
