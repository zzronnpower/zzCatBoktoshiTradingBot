from typing import Any, Dict
from typing_extensions import TypedDict


class CloseRecord(TypedDict, total=False):
    external_id: str
    close_ts: int
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    commission: float
    fees: float
    net: float
    notes: str
    tags: str
    source: str
    close_mode: str
    source_label: str
    close_reason: str
    size_boks: float
    recovered: int
    raw: str
    finalization_state: str
    estimated_source: str


class IntegrityReport(TypedDict, total=False):
    total_rows: int
    duplicate_external_id_count: int
    duplicate_external_ids: list[str]
    stale_pending_count: int
    stale_pending_examples: list[Dict[str, Any]]
    missing_core_fields_count: int
    missing_core_fields_examples: list[Dict[str, Any]]
    source_distribution: Dict[str, int]
    pending_finalize_queue: Dict[str, Dict[str, Any]]


class MetricsPayload(TypedDict, total=False):
    requests: Dict[str, Dict[str, Any]]
    journal_sync: Dict[str, Any]
    remote_history: Dict[str, Any]
    pending_finalize_count: int
    regime_tuning: Dict[str, Any]
