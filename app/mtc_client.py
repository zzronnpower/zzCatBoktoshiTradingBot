import time
from typing import Any, Dict, Optional

import requests


class MTCClientError(Exception):
    def __init__(self, message: str, code: str = "", status_code: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class MTCClient:
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str],
        timeout_seconds: int = 15,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        merged_headers = headers or {}
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=merged_headers,
                    json=json_payload,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if 500 <= resp.status_code < 600 and attempt < self.max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    code = ""
                    message = resp.text
                    try:
                        body = resp.json()
                        code = body.get("code", "")
                        message = body.get("message", message)
                    except Exception:
                        pass
                    raise MTCClientError(message=message, code=code, status_code=resp.status_code)
                return resp.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise MTCClientError(f"Network error: {exc}") from exc
        raise MTCClientError(f"Request failed: {last_error}")

    def register_bot(
        self, name: str, description: str, sponsor_token: str = "", referral_code: str = ""
    ) -> Dict[str, Any]:
        payload = {
            "name": name,
            "description": description,
        }
        if sponsor_token:
            payload["sponsorToken"] = sponsor_token
        if referral_code:
            payload["referralCode"] = referral_code
        return self._request("POST", "/bots/register", json_payload=payload)

    def get_account(self) -> Dict[str, Any]:
        return self._request("GET", "/account", headers=self._headers())

    def get_markets(self) -> Dict[str, Any]:
        return self._request("GET", "/markets")

    def get_positions(self) -> Dict[str, Any]:
        return self._request("GET", "/positions", headers=self._headers())

    def get_history(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/history",
            headers=self._headers(),
            params={"limit": limit, "offset": offset},
        )

    def open_trade(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/trade/open", headers=self._headers(), json_payload=payload)

    def close_trade(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/trade/close", headers=self._headers(), json_payload=payload)

    def close_all_trades(self) -> Dict[str, Any]:
        return self._request("POST", "/trade/close-all", headers=self._headers())

    def daily_claim(self) -> Dict[str, Any]:
        return self._request("POST", "/daily-claim", headers=self._headers())
