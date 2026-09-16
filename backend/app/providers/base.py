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
class _TokenBucket:
    """
    Paces requests to a provider at a fixed rate.

    A semaphore caps how many calls are IN FLIGHT; it says nothing about how
    many start per second. Three concurrent calls that each take 80ms is 37
    requests/second, which is seven times Etherscan's free-tier limit. That
    is why traces were coming back with different node counts each run: some
    calls were being refused, their branch was pruned, and WHICH ones were
    refused changed with network timing.

    Pacing is the fix. Being refused and retrying costs more wall-clock than
    simply not exceeding the limit in the first place.
    """

    def __init__(self, rate_per_second: float):
        self.rate = max(rate_per_second, 0.1)
        self._interval = 1.0 / self.rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = self._next
            self._next = now + self._interval


class HttpClient:
    """
    Shared async client with retry, backoff, a concurrency gate, per-provider
    pacing and a response cache.

    The cache is what makes a trace REPRODUCIBLE within its TTL: re-running
    the same address returns the same upstream payloads, so the same graph,
    rather than a differently-rate-limited sample of it.
    """

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._sem = asyncio.Semaphore(cfg.chain_concurrency)
        self._client: httpx.AsyncClient | None = None
        # One bucket per provider host. Etherscan's limit is per key, and
        # Etherscan V2 serves eth/polygon/bsc off ONE key — so they share a
        # bucket. Getting this wrong is the whole bug.
        self._buckets: dict[str, _TokenBucket] = {
            "etherscan": _TokenBucket(cfg.etherscan_rps),
            "trongrid": _TokenBucket(cfg.trongrid_rps),
            "default": _TokenBucket(cfg.default_provider_rps),
        }
        self._cache: dict[str, tuple[float, Any]] = {}
        self.stats = {"requests": 0, "cache_hits": 0, "rate_limit_retries": 0}

    def _bucket_for(self, url: str) -> _TokenBucket:
        if "etherscan" in url:
            return self._buckets["etherscan"]
        if "trongrid" in url or "trx" in url:
            return self._buckets["trongrid"]
        return self._buckets["default"]

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
        rate_limited: Any = None, cache: bool = True,
    ) -> Any:
        """
        `rate_limited` is a predicate over a decoded 200 body.

        It exists because Etherscan does not answer a rate limit with HTTP
        429. It answers 200 with {"status":"0","message":"Max rate limit
        reached"} — an ordinary success as far as HTTP is concerned. Without
        this hook the retry loop never fired, the caller raised, and the
        address's whole branch silently vanished from the graph.
        """
        if self._client is None:
            raise RuntimeError("HttpClient used outside its context manager")

        ttl = self.cfg.provider_cache_seconds
        if cache and ttl > 0:
            hit = self._cache.get(url)
            if hit and asyncio.get_running_loop().time() - hit[0] < ttl:
                self.stats["cache_hits"] += 1
                return hit[1]

        bucket = self._bucket_for(url)

        async with self._sem:
            last: Exception | None = None
            for attempt in range(self.cfg.provider_retries + 1):
                try:
                    await bucket.acquire()
                    self.stats["requests"] += 1
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
                    body = res.json()

                    if rate_limited is not None and rate_limited(body):
                        self.stats["rate_limit_retries"] += 1
                        raise ProviderError(chain, "provider rate limit (200 body)", 429)

                    if cache and ttl > 0:
                        self._cache[url] = (asyncio.get_running_loop().time(), body)
                    return body
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
class PriceCache:
    """
    Spot price with a TTL, and a last-known fallback.

    A price hiccup must never stall an investigation, so a failed lookup
    reuses the last value rather than raising. Historical cost basis would
    need a per-day series; the API response says plainly that these are
    current spot rates so nobody misreads them.
    """

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._cache: dict[str, tuple[float, float]] = {}

    async def get(self, chain: str, http: HttpClient) -> float:
        coin = NATIVE[chain]["id"]
        hit = self._cache.get(coin)
        now = asyncio.get_event_loop().time()
        if hit and now - hit[1] < self.cfg.price_cache_seconds:
            return hit[0]
        try:
            j = await http.get_json(
                f"{self.cfg.coingecko_url}?ids={coin}&vs_currencies=usd", chain=chain)
            v = float((j or {}).get(coin, {}).get("usd", 0.0))
            if v > 0:
                self._cache[coin] = (v, now)
                return v
        except Exception as e:                       # noqa: BLE001
            log.warning("price lookup failed for %s: %s", coin, e)
        return hit[0] if hit else 0.0

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
