import time
from typing import Any, Dict, List

import requests


class AsterClient:
    def __init__(self, base_url: str = "https://www.asterdex.com", timeout_seconds: int = 12) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "zzCatBoktoshiTradingBot/1.0",
        }
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise RuntimeError(f"ASTER request failed for {path}: {exc}") from exc
        raise RuntimeError(f"ASTER request failed for {path}: {last_error}")

    def get_overview(self, symbol: str = "ETHUSDT") -> Dict[str, Any]:
        ticker = self._get("/fapi/v1/ticker/24hr", {"symbol": symbol})
        premium = self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        open_interest = self._get("/fapi/v1/openInterest", {"symbol": symbol})
        return {
            "symbol": symbol,
            "markPrice": premium.get("markPrice"),
            "indexPrice": premium.get("indexPrice"),
            "lastFundingRate": premium.get("lastFundingRate"),
            "nextFundingTime": premium.get("nextFundingTime"),
            "priceChange": ticker.get("priceChange"),
            "priceChangePercent": ticker.get("priceChangePercent"),
            "lastPrice": ticker.get("lastPrice"),
            "highPrice": ticker.get("highPrice"),
            "lowPrice": ticker.get("lowPrice"),
            "volume": ticker.get("volume"),
            "quoteVolume": ticker.get("quoteVolume"),
            "openInterest": open_interest.get("openInterest"),
            "serverTime": int(time.time() * 1000),
        }

    def get_klines(self, symbol: str = "ETHUSDT", interval: str = "5m", limit: int = 400) -> List[List[Any]]:
        safe_limit = max(50, min(limit, 1000))
        data = self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": safe_limit})
        return data if isinstance(data, list) else []

    def get_depth(self, symbol: str = "ETHUSDT", limit: int = 20) -> Dict[str, Any]:
        safe_limit = max(5, min(limit, 100))
        tries = [safe_limit, 10, 5]
        last_error: Exception | None = None
        for val in tries:
            try:
                data = self._get("/fapi/v1/depth", {"symbol": symbol, "limit": val})
                return data if isinstance(data, dict) else {}
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"ASTER depth failed for {symbol}: {last_error}")
