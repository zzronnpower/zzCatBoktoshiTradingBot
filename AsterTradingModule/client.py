import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from .config import AsterTradingConfig


class AsterTradeError(Exception):
    def __init__(self, message: str, code: int = 0, status_code: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AsterTradeClient:
    def __init__(self, config: AsterTradingConfig) -> None:
        self.config = config
        self.base_url = config.api_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "zzCatBoktoshiTradingBot-ASTER/1.0",
        })

    def _sign(self, query: str) -> str:
        return hmac.new(
            self.config.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        retries: int = 2,
    ) -> Any:
        url = f"{self.base_url}{path}"
        payload: Dict[str, Any] = dict(params or {})
        headers = {}
        if signed:
            if not self.config.api_key or not self.config.api_secret:
                raise AsterTradeError("ASTER API credentials are missing.")
            payload["timestamp"] = int(time.time() * 1000)
            payload.setdefault("recvWindow", self.config.recv_window_ms)
            query = urlencode(payload, doseq=True)
            payload["signature"] = self._sign(query)
            headers["X-MBX-APIKEY"] = self.config.api_key

        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=payload if method.upper() in {"GET", "DELETE"} else None,
                    data=payload if method.upper() in {"POST", "PUT"} else None,
                    headers=headers,
                    timeout=15,
                )
                if response.status_code >= 400:
                    code = 0
                    message = response.text
                    try:
                        body = response.json()
                        code = int(body.get("code", 0))
                        message = body.get("msg", message)
                    except Exception:
                        pass
                    raise AsterTradeError(message=message, code=code, status_code=response.status_code)
                return response.json()
            except (requests.RequestException, AsterTradeError) as exc:
                last_error = exc
                if isinstance(exc, AsterTradeError) and exc.status_code < 500 and exc.status_code not in {429}:
                    raise
                if attempt < retries:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                if isinstance(exc, AsterTradeError):
                    raise
                raise AsterTradeError(f"ASTER request failed: {exc}") from exc
        raise AsterTradeError(f"ASTER request failed: {last_error}")

    def get_exchange_info(self) -> Dict[str, Any]:
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        return data if isinstance(data, dict) else {}

    def get_premium_index(self, symbol: str) -> Dict[str, Any]:
        data = self._request("GET", "/fapi/v1/premiumIndex", params={"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def get_account(self) -> Dict[str, Any]:
        data = self._request("GET", "/fapi/v4/account", signed=True)
        return data if isinstance(data, dict) else {}

    def get_balance(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/fapi/v2/balance", signed=True)
        return data if isinstance(data, list) else []

    def get_positions(self, symbol: str) -> List[Dict[str, Any]]:
        data = self._request("GET", "/fapi/v2/positionRisk", params={"symbol": symbol}, signed=True)
        return data if isinstance(data, list) else []

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        data = self._request("GET", "/fapi/v1/openOrders", params={"symbol": symbol}, signed=True)
        return data if isinstance(data, list) else []

    def get_all_orders(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/fapi/v1/allOrders",
            params={"symbol": symbol, "limit": max(1, min(limit, 1000))},
            signed=True,
        )
        return data if isinstance(data, list) else []

    def get_user_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/fapi/v1/userTrades",
            params={"symbol": symbol, "limit": max(1, min(limit, 1000))},
            signed=True,
        )
        return data if isinstance(data, list) else []

    def get_income(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/fapi/v1/income",
            params={"symbol": symbol, "limit": max(1, min(limit, 1000))},
            signed=True,
        )
        return data if isinstance(data, list) else []

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        data = self._request(
            "POST",
            "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": max(1, min(int(leverage), 125))},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    def place_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        data = self._request("POST", "/fapi/v1/order", params=params, signed=True)
        return data if isinstance(data, dict) else {}

    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        data = self._request(
            "DELETE",
            "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]:
        data = self._request(
            "DELETE",
            "/fapi/v1/allOpenOrders",
            params={"symbol": symbol},
            signed=True,
        )
        return data if isinstance(data, dict) else {}


def floor_to_step(value: float, step_size: str) -> float:
    step = Decimal(step_size)
    if step <= 0:
        return value
    decimal_value = Decimal(str(value))
    normalized = (decimal_value / step).to_integral_value(rounding=ROUND_DOWN) * step
    return float(normalized)


def round_to_tick(value: float, tick_size: str) -> float:
    tick = Decimal(tick_size)
    if tick <= 0:
        return value
    decimal_value = Decimal(str(value))
    normalized = (decimal_value / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return float(normalized)
