import math
from typing import Any, Callable, Dict, List


class JournalAppService:
    def __init__(
        self,
        *,
        get_all_kv: Callable[[], Dict[str, Any]],
        parse_json: Callable[[str], Any],
        trigger_sync: Callable[[bool, bool], bool],
        get_trades: Callable[[int], List[Dict[str, Any]]],
        get_journal_entries: Callable[[int, int, str], List[Dict[str, Any]]],
        count_journal_entries: Callable[[str], int],
        decorate_rows: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
        summarize_rows: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
        integrity_report: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
        load_pending_state: Callable[[], Dict[str, Dict[str, Any]]],
        clear_stale_state: Callable[[int], Dict[str, Any]],
    ) -> None:
        self._get_all_kv = get_all_kv
        self._parse_json = parse_json
        self._trigger_sync = trigger_sync
        self._get_trades = get_trades
        self._get_journal_entries = get_journal_entries
        self._count_journal_entries = count_journal_entries
        self._decorate_rows = decorate_rows
        self._summarize_rows = summarize_rows
        self._integrity_report = integrity_report
        self._load_pending_state = load_pending_state
        self._clear_stale_state = clear_stale_state

    @staticmethod
    def _filter_rows(rows: List[Dict[str, Any]], source: str, state: str, recovered: str) -> List[Dict[str, Any]]:
        source_filter = str(source or "").strip().lower()
        state_filter = str(state or "").strip().upper()
        recovered_filter = str(recovered or "").strip().lower()
        out: List[Dict[str, Any]] = []
        for row in rows:
            if source_filter and source_filter != "all":
                if str(row.get("source_label", "") or "").lower() != source_filter:
                    continue
            if state_filter and state_filter != "ALL":
                if str(row.get("finalization_state", "") or "").upper() != state_filter:
                    continue
            if recovered_filter and recovered_filter != "all":
                want_recovered = recovered_filter in {"1", "true", "yes", "recovered"}
                if bool(int(row.get("recovered", 0) or 0)) != want_recovered:
                    continue
            out.append(row)
        return out

    def get_trade_history_payload(self) -> Dict[str, Any]:
        self._trigger_sync(False, True)
        kv = self._get_all_kv()
        remote = self._parse_json(str(kv.get("last_history", "[]") or "[]"))
        if not isinstance(remote, list):
            remote = []
        closed_items = self._decorate_rows(self._get_journal_entries(2000, 0, ""))
        return {
            "local_exec": self._get_trades(300),
            "remote_history": remote,
            "closed_trades": closed_items,
        }

    def get_journal_page(self, page: int, page_size: int, search: str, source: str, state: str, recovered: str) -> Dict[str, Any]:
        self._trigger_sync(False, True)
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 200))
        safe_search = str(search or "").strip()

        raw_rows = self._get_journal_entries(10000, 0, safe_search)
        filtered = self._filter_rows(self._decorate_rows(raw_rows), source, state, recovered)
        total = len(filtered)
        pages = max(1, math.ceil(total / safe_page_size))
        if safe_page > pages:
            safe_page = pages
        offset = (safe_page - 1) * safe_page_size
        items = filtered[offset : offset + safe_page_size]
        return {
            "items": items,
            "paging": {
                "page": safe_page,
                "page_size": safe_page_size,
                "total": total,
                "pages": pages,
            },
            "search": safe_search,
            "filters": {
                "source": str(source or "").strip().lower() or "all",
                "state": str(state or "").strip().upper() or "ALL",
                "recovered": str(recovered or "").strip().lower() or "all",
            },
        }

    def get_journal_summary(self, search: str, source: str, state: str, recovered: str) -> Dict[str, Any]:
        self._trigger_sync(False, True)
        safe_search = str(search or "").strip()
        total = self._count_journal_entries(safe_search)
        rows = self._get_journal_entries(max(1, min(total, 10000)), 0, safe_search)
        filtered = self._filter_rows(self._decorate_rows(rows), source, state, recovered)
        return {"summary": self._summarize_rows(filtered)}

    def get_integrity_report(self) -> Dict[str, Any]:
        rows = self._decorate_rows(self._get_journal_entries(10000, 0, ""))
        report = self._integrity_report(rows)
        report["pending_finalize_queue"] = self._load_pending_state()
        return {"report": report}

    def clear_stale_pending(self, max_age_sec: int) -> Dict[str, Any]:
        result = self._clear_stale_state(max_age_sec)
        return {"success": True, **result}
