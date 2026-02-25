import app.main as app_main


def test_summarize_journal_rows_uses_display_realized_pnl():
    rows = [
        {
            "size_boks": 1000,
            "commission": 0,
            "fees": 0,
            "display_realized_pnl": 12.5,
            "realized_pnl": None,
            "estimated_realized_pnl": 12.5,
        },
        {
            "size_boks": 500,
            "commission": 0,
            "fees": 0,
            "display_realized_pnl": -7.0,
            "realized_pnl": None,
            "estimated_realized_pnl": -7.0,
        },
        {
            "size_boks": 250,
            "commission": 0,
            "fees": 0,
            "display_realized_pnl": None,
            "realized_pnl": None,
            "estimated_realized_pnl": None,
        },
    ]

    summary = app_main._summarize_journal_rows(rows)

    assert summary["fills"] == 3
    assert summary["size_boks"] == 1750.0
    assert summary["gross"] == 5.5
    assert summary["best"] == 12.5
    assert summary["worst"] == -7.0
    assert summary["wins"] == 1
    assert summary["losses"] == 1


def test_journal_integrity_report_detects_duplicate_stale_and_missing():
    now = 2_000_000
    rows = [
        {
            "external_id": "dup-1",
            "symbol": "ETH",
            "close_ts": now - 5000,
            "pending": 1,
            "source_label": "Manual",
            "entry_price": None,
            "size_boks": None,
        },
        {
            "external_id": "dup-1",
            "symbol": "ETH",
            "close_ts": now - 100,
            "pending": 0,
            "source_label": "Manual",
            "entry_price": 1800,
            "size_boks": 1000,
        },
        {
            "external_id": "ok-1",
            "symbol": "DOGE",
            "close_ts": now - 100,
            "pending": 0,
            "source_label": "Unknown",
            "entry_price": 0.09,
            "size_boks": 1000,
        },
    ]

    report = app_main._journal_integrity_report(rows, now=now)

    assert report["total_rows"] == 3
    assert report["duplicate_external_id_count"] == 1
    assert "dup-1" in report["duplicate_external_ids"]
    assert report["stale_pending_count"] == 1
    assert report["missing_core_fields_count"] >= 2
