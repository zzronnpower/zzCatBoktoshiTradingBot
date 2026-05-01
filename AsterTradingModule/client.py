import time
import threading
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

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
        self._nonce_lock = threading.Lock()
        self._last_nonce = 0

    def _get_nonce(self) -> int:
        with self._nonce_lock:
            now_us = int(time.time() * 1_000_000)
            if now_us <= self._last_nonce:
                now_us = self._last_nonce + 1
            self._last_nonce = now_us
            return now_us

    def _sign(self, query: str) -> str:
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Message": [{"name": "msg", "type": "string"}],
            },
            "primaryType": "Message",
            "domain": {
                "name": self.config.eip712_domain_name,
                "version": self.config.eip712_domain_version,
                "chainId": int(self.config.chain_id),
                "verifyingContract": self.config.verifying_contract,
            },
            "message": {"msg": query},
        }
        message = encode_typed_data(full_message=typed_data)
        signed = Account.sign_message(message, private_key=self.config.signer_private_key)
        return signed.signature.hex()

    def _assert_auth(self) -> None:
        if not self.config.user_address or not self.config.signer_address or not self.config.signer_private_key:
            raise AsterTradeError("ASTER Pro API credentials are missing.")

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
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if signed:
            self._assert_auth()
            payload.setdefault("user", self.config.user_address)
            payload["signer"] = self.config.signer_address
            payload["nonce"] = str(self._get_nonce())
            query = urlencode(payload, doseq=True)
            payload["signature"] = self._sign(query)

        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                upper_method = method.upper()
                response = self.session.request(
                    method=method,
                    url=url,
                    params=payload if upper_method == "GET" else None,
                    data=payload if upper_method in {"POST", "PUT", "DELETE"} else None,
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
        data = self._request("GET", "/fapi/v3/exchangeInfo")
        return data if isinstance(data, dict) else {}

    def get_premium_index(self, symbol: str) -> Dict[str, Any]:
        data = self._request("GET", "/fapi/v3/premiumIndex", params={"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def get_account(self) -> Dict[str, Any]:
        data = self._request("GET", "/fapi/v3/account", signed=True)
        return data if isinstance(data, dict) else {}

    def get_balance(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/fapi/v3/balance", signed=True)
        return data if isinstance(data, list) else []

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        data = self._request("GET", "/fapi/v3/positionRisk", params=params, signed=True)
        return data if isinstance(data, list) else []

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        data = self._request("GET", "/fapi/v3/openOrders", params=params, signed=True)
        return data if isinstance(data, list) else []

    def get_all_orders(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/fapi/v3/allOrders",
            params={"symbol": symbol, "limit": max(1, min(limit, 1000))},
            signed=True,
        )
        return data if isinstance(data, list) else []

    def get_user_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/fapi/v3/userTrades",
            params={"symbol": symbol, "limit": max(1, min(limit, 1000))},
            signed=True,
        )
        return data if isinstance(data, list) else []

    def get_income(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/fapi/v3/income",
            params={"symbol": symbol, "limit": max(1, min(limit, 1000))},
            signed=True,
        )
        return data if isinstance(data, list) else []

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        data = self._request(
            "POST",
            "/fapi/v3/leverage",
            params={"symbol": symbol, "leverage": max(1, min(int(leverage), 125))},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    def place_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        data = self._request("POST", "/fapi/v3/order", params=params, signed=True)
        return data if isinstance(data, dict) else {}

    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        data = self._request(
            "DELETE",
            "/fapi/v3/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        return data if isinstance(data, dict) else {}

    def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]:
        data = self._request(
            "DELETE",
            "/fapi/v3/allOpenOrders",
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
