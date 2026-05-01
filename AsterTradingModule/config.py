import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AsterTradingConfig:
    api_base_url: str = os.getenv("ASTER_TRADE_BASE_URL", "https://fapi.asterdex.com")
    user_address: str = os.getenv("ASTER_USER_ADDRESS", "")
    signer_address: str = os.getenv("ASTER_SIGNER_ADDRESS", "")
    signer_private_key: str = os.getenv("ASTER_SIGNER_PRIVATE_KEY", "")
    chain_id: int = int(os.getenv("ASTER_CHAIN_ID", "1666"))
    recv_window_ms: int = int(os.getenv("ASTER_RECV_WINDOW_MS", "5000"))
    verifying_contract: str = os.getenv("ASTER_VERIFYING_CONTRACT", "0x0000000000000000000000000000000000000000")
    eip712_domain_name: str = os.getenv("ASTER_EIP712_DOMAIN_NAME", "AsterSignTransaction")
    eip712_domain_version: str = os.getenv("ASTER_EIP712_DOMAIN_VERSION", "1")
    default_symbol: str = os.getenv("ASTER_SYMBOL", "ETHUSDT")
    leverage: int = int(os.getenv("ASTER_LEVERAGE", "5"))
    stop_loss_pct: float = float(os.getenv("ASTER_STOP_LOSS_PCT", "0.05"))
    take_profit_pct: float = float(os.getenv("ASTER_TAKE_PROFIT_PCT", "0.15"))
    risk_usdt: float = float(os.getenv("ASTER_RISK_PER_TRADE_USDT", "20"))
    position_notional_usdt: float = float(os.getenv("ASTER_POSITION_NOTIONAL_USDT", "400"))
    margin_per_trade_usdt: float = float(os.getenv("ASTER_MARGIN_PER_TRADE_USDT", "80"))
    max_open_positions: int = int(os.getenv("ASTER_MAX_OPEN_POSITIONS", "2"))
    dry_run: bool = _env_bool("ASTER_DRY_RUN", True)
