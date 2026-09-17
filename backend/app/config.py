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
        env_file=(".env", "backend/.env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
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
    # Each EVM address costs TWO provider calls (txlist + tokentx), so 40
    # per hop over 2 hops is ~160 calls. Etherscan's free tier allows 5/sec,
    # so that trace could not finish in under ~30s and would hit limits
    # mid-run — which is why the node count kept changing between runs.
    max_addresses_per_hop: int = 3
    max_total_edges: int = 1_000
    max_targets_per_request: int = 10
    default_cap_per_address: int = 25
    # Etherscan free tier is 5 requests/second. 6 concurrent guarantees 429s.
    chain_concurrency: int = 3
    provider_timeout_seconds: float = 15.0
    provider_retries: int = 3

    # Requests per second, PER PROVIDER. Concurrency limits how many calls
    # are in flight; it does not limit how many start per second. Three
    # concurrent 80ms calls is 37 req/s — seven times Etherscan's free
    # ceiling. These are the ceilings; the client paces to them.
    #   Etherscan free: 5/s per key, and one key serves eth+polygon+bsc.
    #   TronGrid free:  ~15/s with a key, far less without one.
    etherscan_rps: float = 4.0
    trongrid_rps: float = 8.0
    default_provider_rps: float = 6.0

    # Re-running the same trace inside this window replays cached upstream
    # payloads, so it is FAST and — more importantly — IDENTICAL. Without
    # it, a second run re-samples a rate-limited API and returns a different
    # graph, which makes the tool look like it is guessing.
    provider_cache_seconds: int = 900

    # ---- providers ------------------------------------------------------
    # Bitcoin: Blockstream Esplora, keyless.
    btc_api: str = "https://blockstream.info/api"

    # Ethereum / Polygon / BSC: Etherscan V2 multichain. ONE key covers all
    # of them — chainid selects the chain (1 / 137 / 56). Required.
    etherscan_api: str = "https://api.etherscan.io/v2/api"
    etherscan_api_key: str | None = None

    # Tron: TronGrid. The key is OPTIONAL — the API answers without one, but
    # unkeyed requests are rate-limited hard enough to stall a live trace.
    tron_api: str = "https://api.trongrid.io"
    trongrid_api_key: str | None = None

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
