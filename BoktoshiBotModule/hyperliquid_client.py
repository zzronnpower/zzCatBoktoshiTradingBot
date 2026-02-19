import time
from typing import Any, Dict, List

import requests


class HyperliquidClient:
    def __init__(self, info_url: str = "https://api.hyperliquid.xyz/info") -> None:
        self.info_url = info_url

    def get_candles(self, coin: str, interval: str = "4h", bars: int = 80) -> List[Dict[str, float]]:
        now_ms = int(time.time() * 1000)
        interval_ms = self._interval_to_ms(interval)
        start_ms = now_ms - bars * interval_ms
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": now_ms,
            },
        }
        resp = requests.post(self.info_url, json=payload, timeout=20)
        resp.raise_for_status()
        raw = resp.json()
        candles: List[Dict[str, float]] = []
        for item in raw:
            candles.append(
                {
                    "open_time": float(item.get("t", 0)),
                    "close_time": float(item.get("T", 0)),
                    "open": float(item.get("o", 0)),
                    "high": float(item.get("h", 0)),
                    "low": float(item.get("l", 0)),
                    "close": float(item.get("c", 0)),
                    "volume": float(item.get("v", 0)),
                }
            )
        return candles

    @staticmethod
    def _interval_to_ms(interval: str) -> int:
        mapping = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        if interval not in mapping:
            raise ValueError(f"Unsupported interval: {interval}")
        return mapping[interval]
