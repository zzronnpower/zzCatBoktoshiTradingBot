from AsterTradingModule.client import AsterTradeClient
from AsterTradingModule.config import AsterTradingConfig


class DummyResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "ok"

    def json(self):
        return self._payload


def _config() -> AsterTradingConfig:
    return AsterTradingConfig(
        user_address="0x1111111111111111111111111111111111111111",
        signer_address="0x2222222222222222222222222222222222222222",
        signer_private_key="0x3f85b4f47f58ec7a65a897bce4cd092eb17f68064ea7252ebae08f76f18f66db",
    )


def test_signed_request_includes_pro_auth_payload(monkeypatch):
    client = AsterTradeClient(_config())
    captured = {}

    def _fake_sign(query: str) -> str:
        captured["query"] = query
        return "signed_payload"

    def _fake_request(**kwargs):
        captured["request"] = kwargs
        return DummyResponse(payload={"ok": True})

    monkeypatch.setattr(client, "_get_nonce", lambda: 1773321233000000)
    monkeypatch.setattr(client, "_sign", _fake_sign)
    monkeypatch.setattr(client.session, "request", _fake_request)

    out = client.place_order({"symbol": "ETHUSDT", "side": "BUY", "type": "MARKET", "quantity": 0.1})
    assert out["ok"] is True
    body = captured["request"]["data"]
    assert body["user"] == client.config.user_address
    assert body["signer"] == client.config.signer_address
    assert body["nonce"] == "1773321233000000"
    assert body["signature"] == "signed_payload"
    assert "signature=signed_payload" not in captured["query"]


def test_v3_paths_used_for_trade_and_account_endpoints(monkeypatch):
    client = AsterTradeClient(_config())
    seen = []

    def _fake_request(method, path, params=None, signed=False, retries=2):
        seen.append((method, path, signed))
        if path.endswith("/balance") or path.endswith("/positionRisk") or path.endswith("/openOrders"):
            return []
        return {}

    monkeypatch.setattr(client, "_request", _fake_request)
    client.get_account()
    client.get_balance()
    client.get_positions(None)
    client.get_open_orders(None)
    client.place_order({"symbol": "ETHUSDT", "side": "BUY", "type": "MARKET", "quantity": 0.1})

    paths = [item[1] for item in seen]
    assert "/fapi/v3/account" in paths
    assert "/fapi/v3/balance" in paths
    assert "/fapi/v3/positionRisk" in paths
    assert "/fapi/v3/openOrders" in paths
    assert "/fapi/v3/order" in paths
