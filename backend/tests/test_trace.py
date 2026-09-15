"""
Trace + graph-builder tests.

The provider adapters are verified against the real APIs separately (see
skv-backend/tests/parsers.test.mjs). What is tested here is everything
ABOVE them: hop accounting, edge aggregation, score merging, and the exact
shape React Flow consumes.

The fixture addresses are valid-format BTC addresses, not readable
placeholders like "MULE". They have to be: Target validates every address,
so a test using fake strings never reaches the code under test — which is
exactly what happened on the first run of this file.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.config import get_settings                      # noqa: E402
from app.providers.base import NormEdge                  # noqa: E402
from app.schemas import Target                           # noqa: E402
from app.services.trace import TraceResult, build_graph  # noqa: E402

COLLECTOR = "1CoLLEcToRxxxxxxxxxxxxxxxxxxxxxxx"
MULE      = "1MuLExxxxxxxxxxxxxxxxxxxxxxxxxxxx"
EXCHANGE  = "1ExcHaNGeHoTxxxxxxxxxxxxxxxxxxxxx"
ADDR_A    = "1AaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
ADDR_B    = "1BbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"


def victim(i: int) -> str:
    return f"1VictiM{i}xxxxxxxxxxxxxxxxxxxxxxxxx"


def edge(frm: str, to: str, usd: float, h: str = "tx", day: int = 1) -> NormEdge:
    return NormEdge(
        chain="btc", tx_hash=h, vout_index=0, block_height=900_000,
        block_time=f"2026-09-{day:02d}T00:00:00+00:00",
        from_address=frm, to_address=to,
        value_native=usd / 100_000, value_usd=usd, fee_usd=0.5, asset="BTC",
        raw={"inputs": [frm], "confirmed": True},
    )


TARGETS = [Target(chain="btc", address=COLLECTOR)]


@pytest.fixture
def scenario() -> TraceResult:
    """Victim collection -> mule -> exchange. The PS 26183 fact pattern."""
    edges = [edge(victim(i), COLLECTOR, 500 + i * 10, f"v{i}") for i in range(8)]
    edges += [
        edge(COLLECTOR, MULE, 4200, "sweep"),
        # three transfers on the same pair must collapse into one edge
        edge(MULE, EXCHANGE, 4100, "cashout1", day=1),
        edge(MULE, EXCHANGE, 900, "cashout2", day=2),
        edge(MULE, EXCHANGE, 300, "cashout3", day=3),
    ]
    visited = {f"btc:{COLLECTOR}": 0, f"btc:{MULE}": 1, f"btc:{EXCHANGE}": 2}
    for i in range(8):
        visited[f"btc:{victim(i)}"] = 1
    return TraceResult(edges=edges, visited=visited, prices={"btc": 100_000.0})


def node_for(graph: dict, address: str) -> dict:
    return next(n for n in graph["nodes"] if n["data"]["address"] == address)


# =====================================================================
class TestGraphBuilder:
    def test_produces_react_flow_shape(self, scenario):
        g = build_graph(scenario, TARGETS)
        assert set(g) == {"nodes", "edges"}
        for n in g["nodes"]:
            assert {"id", "type", "data"} <= set(n)
            assert {"address", "chain", "label"} <= set(n["data"])
        for e in g["edges"]:
            assert {"id", "source", "target", "label", "data"} <= set(e)

    def test_parallel_edges_aggregated(self, scenario):
        g = build_graph(scenario, TARGETS)
        me = [e for e in g["edges"]
              if e["source"] == f"btc:{MULE}" and e["target"] == f"btc:{EXCHANGE}"]
        assert len(me) == 1, "3 transfers on one pair must render as 1 edge"
        assert me[0]["data"]["txCount"] == 3
        assert me[0]["data"]["valueUsd"] == pytest.approx(5300.0)

    def test_aggregated_edge_spans_first_to_last(self, scenario):
        g = build_graph(scenario, TARGETS)
        me = next(e for e in g["edges"]
                  if e["source"] == f"btc:{MULE}" and e["target"] == f"btc:{EXCHANGE}")
        assert me["data"]["firstSeen"].startswith("2026-09-01")
        assert me["data"]["lastSeen"].startswith("2026-09-03")

    def test_edge_carries_explorer_links(self, scenario):
        g = build_graph(scenario, TARGETS)
        e = g["edges"][0]
        assert e["data"]["txHashes"]
        assert all(u.startswith("https://blockstream.info/tx/")
                   for u in e["data"]["explorerUrls"])

    def test_node_carries_explorer_link(self, scenario):
        g = build_graph(scenario, TARGETS)
        assert node_for(g, MULE)["data"]["explorerUrl"] == \
            f"https://blockstream.info/address/{MULE}"

    def test_target_flagged_and_typed(self, scenario):
        g = build_graph(scenario, TARGETS)
        t = node_for(g, COLLECTOR)
        assert t["data"]["isTarget"] is True and t["type"] == "target"
        assert all(n["data"]["isTarget"] is False
                   for n in g["nodes"] if n["data"]["address"] != COLLECTOR)

    def test_hop_depth_recorded(self, scenario):
        g = build_graph(scenario, TARGETS)
        assert node_for(g, COLLECTOR)["data"]["hop"] == 0
        assert node_for(g, MULE)["data"]["hop"] == 1
        assert node_for(g, EXCHANGE)["data"]["hop"] == 2

    def test_in_out_totals_correct(self, scenario):
        g = build_graph(scenario, TARGETS)
        c = node_for(g, COLLECTOR)["data"]
        assert c["inUsd"] == pytest.approx(sum(500 + i * 10 for i in range(8)))
        assert c["outUsd"] == pytest.approx(4200.0)

    def test_degree_counted(self, scenario):
        g = build_graph(scenario, TARGETS)
        # 8 inbound victims + 1 outbound to the mule
        assert node_for(g, COLLECTOR)["data"]["degree"] == 9

    def test_large_transfers_animated(self):
        big = TraceResult(edges=[edge(ADDR_A, ADDR_B, 50_000, "big")],
                          visited={f"btc:{ADDR_A}": 0}, prices={"btc": 1.0})
        g = build_graph(big, [Target(chain="btc", address=ADDR_A)])
        assert g["edges"][0]["animated"] is True

    def test_small_transfers_not_animated(self, scenario):
        g = build_graph(scenario, TARGETS)
        victim_edges = [e for e in g["edges"] if e["target"] == f"btc:{COLLECTOR}"]
        assert victim_edges and all(e["animated"] is False for e in victim_edges)

    def test_scores_merge_into_nodes(self, scenario):
        scores = {MULE: {
            "address": MULE, "risk_score": 82.5, "risk_band": "critical",
            "narrative": "Pass-through wallet retaining almost nothing.",
            "typologies": [{"typology": "mule", "confidence": 0.91}],
            "recommended_actions": ["Preserve pre-mixer evidence."],
            "hops_to_exchange": 1, "hops_to_sanctioned": None,
            "vasp_attribution": {"type": "p2p", "confidence": 0.7, "abstained": False},
        }}
        g = build_graph(scenario, TARGETS, scores=scores)
        m = node_for(g, MULE)
        assert m["data"]["riskScore"] == 82.5
        assert m["data"]["riskBand"] == "critical"
        assert m["data"]["hopsToExchange"] == 1
        assert m["data"]["typologies"][0]["typology"] == "mule"
        assert m["data"]["recommendedActions"]
        assert m["type"] == "p2p"

    def test_abstained_vasp_does_not_set_entity(self, scenario):
        """An abstention must not be rendered as a confident label."""
        scores = {MULE: {"address": MULE, "risk_score": 40.0, "risk_band": "medium",
                         "vasp_attribution": {"type": "exchange", "confidence": 0.2,
                                              "abstained": True}}}
        g = build_graph(scenario, TARGETS, scores=scores)
        assert node_for(g, MULE)["data"]["entity"] == "unknown"

    def test_wallet_labels_merge(self, scenario):
        wallets = {f"btc:{EXCHANGE}": {
            "chain": "btc", "address": EXCHANGE, "entity_type": "exchange",
            "vasp_name": "WazirX", "is_sanctioned": False}}
        g = build_graph(scenario, TARGETS, wallets=wallets)
        x = node_for(g, EXCHANGE)
        assert x["data"]["vaspName"] == "WazirX"
        assert x["data"]["label"] == "WazirX"
        assert x["type"] == "exchange"

    def test_sanctioned_flag_surfaces(self, scenario):
        wallets = {f"btc:{MULE}": {"chain": "btc", "address": MULE,
                                   "entity_type": "sanctioned", "is_sanctioned": True}}
        g = build_graph(scenario, TARGETS, wallets=wallets)
        assert node_for(g, MULE)["data"]["sanctioned"] is True

    def test_empty_trace_yields_empty_graph(self):
        assert build_graph(TraceResult(), TARGETS) == {"nodes": [], "edges": []}

    def test_every_edge_endpoint_exists_as_node(self, scenario):
        """A dangling edge reference crashes React Flow — guard against it."""
        g = build_graph(scenario, TARGETS)
        ids = {n["id"] for n in g["nodes"]}
        for e in g["edges"]:
            assert e["source"] in ids, f"dangling source {e['source']}"
            assert e["target"] in ids, f"dangling target {e['target']}"

    def test_node_ids_unique(self, scenario):
        g = build_graph(scenario, TARGETS)
        ids = [n["id"] for n in g["nodes"]]
        assert len(ids) == len(set(ids))

    def test_node_count_matches_participants(self, scenario):
        g = build_graph(scenario, TARGETS)
        assert len(g["nodes"]) == 8 + 3      # victims + collector + mule + exchange


class TestLimits:
    def test_config_caps_are_sane(self):
        cfg = get_settings()
        assert cfg.max_hops <= 3
        assert cfg.max_addresses_per_hop <= 100
        assert cfg.chain_concurrency <= 10, "too much concurrency trips the free tiers"
        assert cfg.trace_rate_limit_requests < cfg.rate_limit_requests
