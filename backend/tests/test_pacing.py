"""
Provider pacing, caching and the 200-body rate limit.

These three together are why the same trace returned 160 nodes, then 260,
then 80. Concurrency limited how many calls were IN FLIGHT and nothing
limited how many started per second; Etherscan refused the overflow with an
HTTP 200 the retry loop could not see; the refused address's branch was
pruned; and WHICH branch got pruned changed with network timing.

So the guarantees under test are:
  * the client paces to the configured rate rather than bursting,
  * a 200-body rate limit is retried, not swallowed,
  * an identical request inside the TTL replays, so a re-run is identical.
"""
from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.config import Settings                              # noqa: E402
from app.providers.base import HttpClient, ProviderError, _TokenBucket  # noqa: E402
from app.providers.adapters import (                         # noqa: E402
    _etherscan_rate_limited, _trongrid_rate_limited,
)


def _runs_async(fn):
    """
    asyncio.run instead of pytest-asyncio.

    The suite deliberately has no plugin dependency for this; one decorator
    is cheaper than a package every contributor has to install.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return wrapper


# =====================================================================
# The predicate. Getting this wrong is the whole bug: "No transactions
# found" is ALSO status 0, and treating it as a rate limit would retry
# three times on every empty address and slow every trace down.
# =====================================================================
def test_max_rate_limit_body_is_detected():
    assert _etherscan_rate_limited(
        {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"})


def test_max_calls_per_sec_body_is_detected():
    assert _etherscan_rate_limited(
        {"status": "0", "message": "NOTOK",
         "result": "Max calls per sec rate limit reached (5/sec)"})


def test_empty_address_is_not_a_rate_limit():
    assert not _etherscan_rate_limited(
        {"status": "0", "message": "No transactions found", "result": []})


def test_success_is_not_a_rate_limit():
    assert not _etherscan_rate_limited({"status": "1", "message": "OK", "result": [{}]})


def test_non_dict_is_not_a_rate_limit():
    assert not _etherscan_rate_limited(None)
    assert not _etherscan_rate_limited("Max rate limit reached")


def test_trongrid_rate_limit_body():
    assert _trongrid_rate_limited({"Error": "request rate limit exceeded"})
    assert not _trongrid_rate_limited({"data": []})


# =====================================================================
# Pacing
# =====================================================================
@_runs_async
async def test_token_bucket_paces_to_the_configured_rate():
    bucket = _TokenBucket(rate_per_second=20.0)      # 50ms apart
    loop = asyncio.get_running_loop()
    start = loop.time()
    for _ in range(5):
        await bucket.acquire()
    elapsed = loop.time() - start
    # 5 acquisitions at 20/s is 4 gaps = 200ms. Allow slack for scheduling,
    # but it must NOT be instant — instant is the bug.
    assert elapsed >= 0.15, f"bucket did not pace: {elapsed:.3f}s for 5 calls"


@_runs_async
async def test_token_bucket_paces_concurrent_callers_too():
    """A semaphore caps in-flight calls; only the bucket caps the RATE."""
    bucket = _TokenBucket(rate_per_second=20.0)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.gather(*(bucket.acquire() for _ in range(5)))
    assert loop.time() - start >= 0.15


def test_etherscan_and_evm_chains_share_one_bucket():
    """
    Etherscan V2 serves eth, polygon and bsc off ONE key, so the limit is
    per key, not per chain. Separate buckets would burst 3x the ceiling.
    """
    cfg = Settings(etherscan_api_key="k")
    client = HttpClient(cfg)
    eth = client._bucket_for("https://api.etherscan.io/v2/api?chainid=1")
    pol = client._bucket_for("https://api.etherscan.io/v2/api?chainid=137")
    bsc = client._bucket_for("https://api.etherscan.io/v2/api?chainid=56")
    assert eth is pol is bsc
    assert client._bucket_for("https://api.trongrid.io/v1/x") is not eth


def test_configured_rate_is_under_the_free_tier_ceiling():
    """Etherscan free tier is 5/sec. Pacing AT the ceiling still gets 429s."""
    cfg = Settings()
    assert cfg.etherscan_rps < 5.0


# =====================================================================
# Retry + cache, against a stub transport
# =====================================================================
class _StubResponse:
    def __init__(self, body, status_code=200):
        self._body, self.status_code, self.text = body, status_code, str(body)

    def json(self):
        return self._body


class _StubClient:
    """Counts calls, so we can prove a retry happened and a cache hit did not."""

    def __init__(self, bodies):
        self.bodies, self.calls = list(bodies), 0

    async def get(self, url, headers=None):
        self.calls += 1
        return _StubResponse(self.bodies[min(self.calls - 1, len(self.bodies) - 1)])


@_runs_async
async def test_rate_limited_body_is_retried_not_returned():
    limited = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    good = {"status": "1", "message": "OK", "result": [{"hash": "0xabc"}]}

    cfg = Settings(etherscan_rps=200.0, provider_retries=3)
    client = HttpClient(cfg)
    client._client = _StubClient([limited, limited, good])

    body = await client.get_json("https://api.etherscan.io/v2/api?chainid=137",
                                 chain="polygon",
                                 rate_limited=_etherscan_rate_limited)
    assert body == good
    assert client._client.calls == 3, "the 200-body rate limit was not retried"
    assert client.stats["rate_limit_retries"] == 2


@_runs_async
async def test_persistent_rate_limit_raises_rather_than_returning_empty():
    """
    The failure mode that made node counts wander: a refused address that
    looks like an address with no transactions. It must RAISE, so the trace
    records it as unreachable instead of as empty.
    """
    limited = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    cfg = Settings(etherscan_rps=200.0, provider_retries=1)
    client = HttpClient(cfg)
    client._client = _StubClient([limited])

    with pytest.raises(ProviderError):
        await client.get_json("https://api.etherscan.io/v2/api", chain="polygon",
                              rate_limited=_etherscan_rate_limited)


@_runs_async
async def test_identical_request_is_served_from_cache():
    """This is what makes a re-run of the same trace return the same graph."""
    good = {"status": "1", "result": [{"hash": "0xabc"}]}
    cfg = Settings(etherscan_rps=200.0, provider_cache_seconds=900)
    client = HttpClient(cfg)
    client._client = _StubClient([good])

    url = "https://api.etherscan.io/v2/api?chainid=137&address=0xabc"
    first = await client.get_json(url, chain="polygon")
    second = await client.get_json(url, chain="polygon")

    assert first == second
    assert client._client.calls == 1, "the second identical call hit the network"
    assert client.stats["cache_hits"] == 1


@_runs_async
async def test_cache_can_be_disabled_per_call():
    good = {"status": "1", "result": []}
    cfg = Settings(etherscan_rps=200.0)
    client = HttpClient(cfg)
    client._client = _StubClient([good])
    url = "https://api.etherscan.io/v2/api?x=1"
    await client.get_json(url, chain="polygon", cache=False)
    await client.get_json(url, chain="polygon", cache=False)
    assert client._client.calls == 2
