"""
Configuration — environment only, no secrets in code.

Fail-closed by design: SUPABASE_URL and SUPABASE_JWT_SECRET (or the anon key)
have no defaults. A deployment that forgets them refuses to start rather than
booting with authentication quietly disabled, which is the failure mode your
report commits to eliminating.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Chain = Literal["btc", "eth", "polygon", "tron", "bsc"]
ALLOWED_CHAINS: set[str] = {"btc", "eth", "polygon", "tron", "bsc"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- identity -----------------------------------------------------
    app_name: str = "Chakravyuh SETU API"
    version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"

    # ---- Supabase (required) ------------------------------------------
    supabase_url: str = Field(..., description="https://<ref>.supabase.co")
    supabase_anon_key: str = Field(...)
    supabase_service_role_key: str | None = Field(
        default=None,
        description="Server-side only. Never sent to a browser.",
    )

    # ---- service-to-service auth --------------------------------------
    service_api_key: str | None = Field(
        default=None,
        description="Optional shared secret for machine callers. Compared in "
                    "constant time; a short or absent value disables the path.",
    )

    # ---- CORS ----------------------------------------------------------
    cors_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated. '*' is refused in production.",
    )

    # ---- rate limiting -------------------------------------------------
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    trace_rate_limit_requests: int = 10          # tracing is expensive upstream

    # ---- tracing limits ------------------------------------------------
    max_hops: int = 3
    max_addresses_per_hop: int = 40
    max_total_edges: int = 8_000
    max_targets_per_request: int = 10
    default_cap_per_address: int = 50
    chain_concurrency: int = 6
    provider_timeout_seconds: float = 15.0
    provider_retries: int = 3

    # ---- providers ------------------------------------------------------
    btc_api: str = "https://blockstream.info/api"
    eth_api: str = "https://eth.blockscout.com/api/v2"
    polygon_api: str = "https://polygon.blockscout.com/api/v2"
    tron_api: str = "https://apilist.tronscanapi.com"
    etherscan_api_key: str | None = None          # required for BSC only
    tronscan_api_key: str | None = None           # optional, raises Tron limits
    coingecko_url: str = "https://api.coingecko.com/api/v3/simple/price"
    price_cache_seconds: int = 300

    # ---- ML service ------------------------------------------------------
    ml_api_url: str | None = None
    ml_api_key: str | None = None
    ml_timeout_seconds: float = 25.0

    # ---- threat intel -----------------------------------------------------
    ofac_base_url: str = (
        "https://raw.githubusercontent.com/0xB10C/"
        "ofac-sanctioned-digital-currency-addresses/lists"
    )
    threat_feed_url: str | None = None

    # ------------------------------------------------------------------
    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_in_prod(cls, v: str, info) -> str:
        env = (info.data or {}).get("environment")
        if env == "production" and "*" in v:
            raise ValueError(
                "cors_origins='*' is not permitted in production. "
                "List your frontend origins explicitly."
            )
        return v

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_service_key(self) -> bool:
        # A 1-character "key" is worse than none: it looks configured while
        # being trivially guessable. Refuse anything under 32 chars.
        return bool(self.service_api_key and len(self.service_api_key) >= 32)


@lru_cache
def get_settings() -> Settings:
    return Settings()
