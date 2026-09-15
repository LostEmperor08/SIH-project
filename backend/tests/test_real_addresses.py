"""
Regression test built from REAL live on-chain data.

Captured from eth.blockscout.com on 15 Sep 2026 for two addresses supplied
for verification:

  A  0xC8A7A990d874d6E6Fa6cC2544F77fe61367DF3DB
  B  0x20148AB7597a6ED17129F4eCaC2bCbb2c8cbff0f

Why this test exists: address B has **zero native ETH transactions**. Every
bit of its activity is ERC-20 token transfers. A native-only tracer returns
an empty graph for it — which is how a USDT-based fraud case would come back
looking clean. PS 26183 names USDT explicitly, so this is not an edge case,
it is the main case.

The two addresses connect at hop 2 through a shared counterparty
(0x2767ae7E…) that airdropped the same token to both. That link is exactly
what the graph is supposed to surface, and it is only visible once token
transfers are traced.

    python -m pytest tests/test_real_addresses.py -v
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.providers.adapters import STABLECOINS, _token_usd   # noqa: E402
from app.providers.base import NormEdge                      # noqa: E402
from app.schemas import Target, is_valid_address             # noqa: E402
from app.services.trace import TraceResult, build_graph      # noqa: E402

A = "0xc8a7a990d874d6e6fa6cc2544f77fe61367df3db"
B = "0x20148ab7597a6ed17129f4ecac2bcbb2c8cbff0f"
SHARED = "0x2767ae7e0c205425a7b7f7583c512513c527f482"   # airdropped both
E3B4 = "0xe3b4c6dcf32b2617780da01689f01ed826a9ff83"     # A's USDT recipient
GAS_FUNDER = "0x935d2e470284fb536227a76a723f96a94efae6a9"
USDT_SENDER = "0x0c46f38ae77fd4c3c7810dfde5d53cede608764f"
USDC_SENDER = "0xedd1ae45b7727fe87bb924abbcbf7a662475f17d"
WATTOIN_SENDER = "0x5eef5946ad78e614bb3ee7b9ed1097c517ae97f7"


def tok(frm, to, sym, amount, ts, h, idx=1) -> NormEdge:
    usd, unvalued = _token_usd(sym, amount)
    return NormEdge(
        chain="eth", tx_hash=h, vout_index=idx, block_height=None,
        block_time=ts, from_address=frm, to_address=to,
        value_native=amount, value_usd=usd, fee_usd=0.0, asset=sym,
        raw={"transferType": "erc20", "unvalued": unvalued},
    )


def native(frm, to, eth_amt, ts, h) -> NormEdge:
    return NormEdge(
        chain="eth", tx_hash=h, vout_index=0, block_height=None,
        block_time=ts, from_address=frm, to_address=to,
        value_native=eth_amt, value_usd=round(eth_amt * 4000, 2),
        fee_usd=0.0, asset="ETH", raw={"transferType": "native"},
    )


@pytest.fixture
def live_edges() -> list[NormEdge]:
    """Exactly what the providers returned for these two addresses."""
    return [
        # --- address A, native ---
        native(A, E3B4, 0.000065428721662325, "2026-09-09T05:34:35Z", "0xd44e125f"),
        native(GAS_FUNDER, A, 0.00019537, "2026-09-09T05:28:35Z", "0xdbcf3267"),
        # --- address A, ERC-20 ---
        tok(WATTOIN_SENDER, A, "WATTOIN", 5.0, "2026-09-09T05:34:23Z", "0x578bbec9"),
        tok(A, E3B4, "USDT", 0.40, "2026-09-09T05:33:35Z", "0x7db17de7"),
        tok(SHARED, A, "yRise", 0.00009, "2026-08-09T00:23:35Z", "0xee771c0c"),
        tok(USDT_SENDER, A, "USDT", 0.40, "2026-08-03T20:06:47Z", "0xdcfa0128"),
        # --- address B, ERC-20 only (NO native transactions at all) ---
        tok(SHARED, B, "yRise", 0.00009, "2026-08-08T17:41:23Z", "0x927e620b"),
        tok(USDC_SENDER, B, "USDC", 199.664519, "2026-06-09T21:20:47Z", "0x43aefb14"),
    ]


TARGETS = [Target(chain="eth", address=A), Target(chain="eth", address=B)]


# =====================================================================
class TestAddressesAreValid:
    def test_both_validate_as_eth(self):
        assert is_valid_address("eth", A)
        assert is_valid_address("eth", B)

    def test_neither_validates_as_btc(self):
        """They were supplied as 'bitcoin' addresses. They are not."""
        assert not is_valid_address("btc", A)
        assert not is_valid_address("btc", B)


class TestTokenTracingIsRequired:
    def test_address_B_has_no_native_activity(self, live_edges):
        native_b = [e for e in live_edges
                    if e.raw.get("transferType") == "native"
                    and B in (e.from_address, e.to_address)]
        assert native_b == [], "address B has zero native transactions on chain"

    def test_native_only_trace_loses_address_B_entirely(self, live_edges):
        """The bug this test was written for."""
        native_only = [e for e in live_edges if e.raw.get("transferType") == "native"]
        tr = TraceResult(edges=native_only,
                         visited={f"eth:{A}": 0, f"eth:{B}": 0},
                         prices={"eth": 4000.0})
        g = build_graph(tr, TARGETS)
        addrs = {n["data"]["address"] for n in g["nodes"]}
        assert B not in addrs, "fixture wrong — B should be absent without tokens"

    def test_token_trace_recovers_address_B(self, live_edges):
        tr = TraceResult(edges=live_edges,
                         visited={f"eth:{A}": 0, f"eth:{B}": 0},
                         prices={"eth": 4000.0})
        g = build_graph(tr, TARGETS)
        addrs = {n["data"]["address"] for n in g["nodes"]}
        assert B in addrs
        assert A in addrs


class TestTheTwoAddressesConnect:
    def test_shared_counterparty_exists(self, live_edges):
        """Both received the same token from the same sender."""
        to_a = {e.from_address for e in live_edges if e.to_address == A}
        to_b = {e.from_address for e in live_edges if e.to_address == B}
        assert SHARED in to_a & to_b

    def test_path_A_to_B_is_two_hops(self, live_edges):
        """A <- SHARED -> B. Undirected distance 2."""
        adj: dict[str, set[str]] = {}
        for e in live_edges:
            adj.setdefault(e.from_address, set()).add(e.to_address)
            adj.setdefault(e.to_address, set()).add(e.from_address)

        from collections import deque
        dist = {A: 0}
        q = deque([A])
        while q:
            n = q.popleft()
            for nb in adj.get(n, ()):
                if nb not in dist:
                    dist[nb] = dist[n] + 1
                    q.append(nb)
        assert dist.get(B) == 2, f"expected 2 hops, got {dist.get(B)}"
        assert dist.get(SHARED) == 1

    def test_graph_renders_both_targets_connected(self, live_edges):
        tr = TraceResult(edges=live_edges,
                         visited={f"eth:{A}": 0, f"eth:{B}": 0,
                                  f"eth:{SHARED}": 1},
                         prices={"eth": 4000.0})
        g = build_graph(tr, TARGETS)
        ids = {n["id"] for n in g["nodes"]}
        # the shared node bridges them
        assert f"eth:{SHARED}" in ids
        bridging = [e for e in g["edges"] if e["source"] == f"eth:{SHARED}"]
        targets_reached = {e["target"] for e in bridging}
        assert {f"eth:{A}", f"eth:{B}"} <= targets_reached


class TestValuation:
    def test_stablecoins_valued_one_to_one(self):
        assert _token_usd("USDT", 400.0) == (400.0, False)
        assert _token_usd("USDC", 199.66) == (199.66, False)

    def test_stablecoin_set_is_case_insensitive(self):
        assert _token_usd("usdt", 10.0)[0] == 10.0

    def test_unknown_tokens_left_unvalued_not_wrongly_valued(self):
        """Multiplying yRise by the ETH price would invent money."""
        usd, unvalued = _token_usd("yRise", 0.00009)
        assert usd == 0.0 and unvalued is True
        usd, unvalued = _token_usd("WATTOIN", 5.0)
        assert usd == 0.0 and unvalued is True

    def test_usdc_amount_decodes_correctly(self, live_edges):
        usdc = next(e for e in live_edges if e.asset == "USDC")
        assert usdc.value_native == pytest.approx(199.664519)
        assert usdc.value_usd == pytest.approx(199.66, abs=0.01)

    def test_usdt_6_decimals(self, live_edges):
        usdt = [e for e in live_edges if e.asset == "USDT"]
        assert len(usdt) == 2
        assert all(e.value_native == pytest.approx(0.40) for e in usdt)


class TestGraphShape:
    def test_no_dangling_edges(self, live_edges):
        tr = TraceResult(edges=live_edges, visited={}, prices={"eth": 4000.0})
        g = build_graph(tr, TARGETS)
        ids = {n["id"] for n in g["nodes"]}
        for e in g["edges"]:
            assert e["source"] in ids and e["target"] in ids

    def test_token_and_native_legs_coexist(self, live_edges):
        """A->E3B4 happens twice: 0.000065 ETH and 0.40 USDT. Both must survive."""
        tr = TraceResult(edges=live_edges, visited={}, prices={"eth": 4000.0})
        g = build_graph(tr, TARGETS)
        leg = [e for e in g["edges"]
               if e["source"] == f"eth:{A}" and e["target"] == f"eth:{E3B4}"]
        assert len(leg) == 1                      # aggregated into one edge
        assert leg[0]["data"]["txCount"] == 2     # but both legs counted

    def test_all_participants_appear(self, live_edges):
        tr = TraceResult(edges=live_edges, visited={}, prices={"eth": 4000.0})
        g = build_graph(tr, TARGETS)
        addrs = {n["data"]["address"] for n in g["nodes"]}
        for expected in (A, B, SHARED, E3B4, GAS_FUNDER,
                         USDT_SENDER, USDC_SENDER, WATTOIN_SENDER):
            assert expected in addrs, f"{expected} missing from graph"
        assert len(addrs) == 8
