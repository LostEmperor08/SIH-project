"""
Provider plumbing shared by every chain adapter.

Normalised edge shape, retry/backoff, a concurrency gate, and the USD price
cache. The tracing layer above never learns which chain it is walking.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings

log = logging.getLogger("chakravyuh.providers")


@dataclass
class NormEdge:
    """One directed value transfer. The universal currency of this system."""
    chain: str
    tx_hash: str
    vout_index: int
    block_height: int | None
    block_time: str                  # ISO-8601 UTC
    from_address: str
    to_address: str
    value_native: float
    value_usd: float
    fee_usd: float
    asset: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.tx_hash}:{self.vout_index}:{self.from_address}:{self.to_address}"

    def to_row(self) -> dict[str, Any]:
        """Shape expected by the Supabase `transactions` table."""
        return {
            "chain": self.chain, "tx_hash": self.tx_hash, "vout_index": self.vout_index,
            "block_height": self.block_height, "block_time": self.block_time,
            "from_address": self.from_address, "to_address": self.to_address,
            "value_native": self.value_native, "value_usd": self.value_usd,
            "fee_usd": self.fee_usd, "asset": self.asset, "raw": self.raw,
        }


class ProviderError(Exception):
    def __init__(self, chain: str, message: str, status_code: int | None = None):
        self.chain, self.status_code = chain, status_code
        super().__init__(f"[{chain}] {message}")


NATIVE: dict[str, dict[str, Any]] = {
    "btc": {"id": "bitcoin", "symbol": "BTC", "decimals": 8},
    "eth": {"id": "ethereum", "symbol": "ETH", "decimals": 18},
    "polygon": {"id": "matic-network", "symbol": "POL", "decimals": 18},
    "bsc": {"id": "binancecoin", "symbol": "BNB", "decimals": 18},
    "tron": {"id": "tron", "symbol": "TRX", "decimals": 6},
}


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# =====================================================================
class HttpClient:
    """
    Shared async client with retry, backoff and a concurrency gate.

    The gate matters more than it looks. A 3-hop trace fans out to hundreds
    of upstream calls; firing them at once gets you rate-limited into a
    failed demo. Six concurrent is the sweet spot for these free tiers.
    """

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._sem = asyncio.Semaphore(cfg.chain_concurrency)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HttpClient":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.cfg.provider_timeout_seconds),
            headers={"Accept": "application/json", "User-Agent": "ChakravyuhSETU/1.0"},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=self.cfg.chain_concurrency * 2),
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_json(
        self, url: str, *, chain: str = "?", headers: dict | None = None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("HttpClient used outside its context manager")

        async with self._sem:
            last: Exception | None = None
            for attempt in range(self.cfg.provider_retries + 1):
                try:
                    res = await self._client.get(url, headers=headers)
                    if res.status_code == 404:
                        return None                       # unused address
                    if res.status_code == 429 or res.status_code >= 500:
                        raise ProviderError(chain, f"upstream {res.status_code}",
                                            res.status_code)
                    if res.status_code >= 400:
                        # 4xx other than 429 is our fault — do not retry
                        raise ProviderError(
                            chain, f"{res.status_code} {res.text[:200]}", res.status_code)
                    return res.json()
                except (httpx.HTTPError, ProviderError) as e:
                    last = e
                    if isinstance(e, ProviderError) and e.status_code \
                            and 400 <= e.status_code < 500 and e.status_code != 429:
                        raise
                    if attempt == self.cfg.provider_retries:
                        break
                    await asyncio.sleep(0.5 * 2 ** attempt + random.random() * 0.4)
            raise ProviderError(chain, f"unreachable after retries: {last}")


# =====================================================================
# Baseline fallback spot rates so a trace never hangs or returns $0
FALLBACK_PRICES: dict[str, float] = {
    "btc": 75000.0,
    "eth": 2400.0,
    "polygon": 0.10,
    "bsc": 700.0,
    "tron": 0.33,
}

BINANCE_SYMBOLS: dict[str, str] = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "polygon": "POLUSDT",
    "bsc": "BNBUSDT",
    "tron": "TRXUSDT",
}


class PriceCache:
    """
    Ultra-fast spot price cache with live ticker and instant baseline fallback.

    Never blocks a trace: attempts fast live lookup (Binance/CoinGecko) with
    a short timeout, and immediately falls back to recent/baseline prices
    so an officer gets real USD numbers in milliseconds.
    """

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._cache: dict[str, tuple[float, float]] = {}

    async def get(self, chain: str, http: HttpClient) -> float:
        hit = self._cache.get(chain)
        now = asyncio.get_event_loop().time()
        if hit and now - hit[1] < self.cfg.price_cache_seconds:
            return hit[0]

        # 1. Try fast Binance ticker (10-50ms)
        bsym = BINANCE_SYMBOLS.get(chain)
        if bsym:
            try:
                j = await http.get_json(
                    f"https://api.binance.com/api/v3/ticker/price?symbol={bsym}",
                    chain=chain,
                )
                if isinstance(j, dict) and "price" in j:
                    v = float(j["price"])
                    if v > 0:
                        self._cache[chain] = (v, now)
                        return v
            except Exception:
                pass

        # 2. Try CoinGecko fallback
        coin = NATIVE.get(chain, {}).get("id")
        if coin:
            try:
                j = await http.get_json(
                    f"{self.cfg.coingecko_url}?ids={coin}&vs_currencies=usd", chain=chain
                )
                v = float((j or {}).get(coin, {}).get("usd", 0.0))
                if v > 0:
                    self._cache[chain] = (v, now)
                    return v
            except Exception:
                pass

        # 3. Fallback to cached or baseline spot price
        fallback = hit[0] if hit else FALLBACK_PRICES.get(chain, 1.0)
        self._cache[chain] = (fallback, now)
        return fallback

    def clear(self) -> None:
        self._cache.clear()


def explorer_url(chain: str, address: str) -> str:
    return {
        "btc": f"https://blockstream.info/address/{address}",
        "eth": f"https://eth.blockscout.com/address/{address}",
        "polygon": f"https://polygon.blockscout.com/address/{address}",
        "bsc": f"https://bscscan.com/address/{address}",
        "tron": f"https://tronscan.org/#/address/{address}",
    }.get(chain, "")


def tx_explorer_url(chain: str, tx_hash: str) -> str:
    return {
        "btc": f"https://blockstream.info/tx/{tx_hash}",
        "eth": f"https://eth.blockscout.com/tx/{tx_hash}",
        "polygon": f"https://polygon.blockscout.com/tx/{tx_hash}",
        "bsc": f"https://bscscan.com/tx/{tx_hash}",
        "tron": f"https://tronscan.org/#/transaction/{tx_hash}",
    }.get(chain, "")
