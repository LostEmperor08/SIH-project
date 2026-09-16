"""
Risk engine tests.

The scoring path must work with no database and no ML service, because an
officer pasting an address has to get a scored graph either way. These tests
run it in complete isolation — no network, no Supabase, no models.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.providers.base import NormEdge            # noqa: E402
from app.services.risk import (                    # noqa: E402
    BAND_CRITICAL, BAND_HIGH, build_stats, score_graph,
)

NOW = datetime.now(timezone.utc)


def ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def edge(frm, to, usd, days_ago=1.0, asset="USDT", h=None, unvalued=False):
    return NormEdge(
        chain="eth", tx_hash=h or f"0x{abs(hash((frm, to, usd))) % 10**12:012x}",
        vout_index=0, block_height=None, block_time=ts(days_ago),
        from_address=frm, to_address=to,
        value_native=usd, value_usd=usd, fee_usd=0.0, asset=asset,
        raw={"transferType": "erc20", "unvalued": unvalued},
    )


VICTIM = [f"0xv{i:039x}" for i in range(30)]
COLLECTOR = "0xc" + "0" * 39
MULE = "0xm" + "0" * 39
MIXER = "0xx" + "0" * 39
EXCHANGE = "0xe" + "0" * 39
SANCTIONED = "0xs" + "0" * 39
CLEAN = "0xq" + "0" * 39


# =====================================================================
class TestAlwaysAvailable:
    def test_empty_graph_returns_empty_not_fabricated(self):
        assert score_graph([], []) == {}

    def test_needs_no_db_or_ml(self):
        """No mocks, no patches — it simply runs."""
        res = score_graph([edge("0xa" + "0"*39, "0xb" + "0"*39, 100)], [])
        assert len(res) == 2
        assert all("risk_score" in r for r in res.values())

    def test_every_wallet_gets_a_band(self):
        res = score_graph([edge(v, COLLECTOR, 500) for v in VICTIM[:5]], [COLLECTOR])
        for r in res.values():
            assert r["risk_band"] in ("low", "medium", "high", "critical")
            assert 0 <= r["risk_score"] <= 100


class TestSanctions:
    def test_direct_hit_pins_to_90_minimum(self):
        edges = [edge(CLEAN, SANCTIONED, 50)]
        res = score_graph(edges, [], sanctioned={SANCTIONED})
        s = res[SANCTIONED]
        assert s["risk_score"] >= 90
        assert s["risk_band"] == "critical"
        assert s["sanction_floor_applied"] is True

    def test_one_hop_scores_but_below_floor(self):
        edges = [edge(CLEAN, SANCTIONED, 50)]
        res = score_graph(edges, [], sanctioned={SANCTIONED})
        c = res[CLEAN]
        assert c["hops_to_sanctioned"] == 1
        assert any(f["code"] == "SANCTION_1HOP" for f in c["factors"])
        assert c["sanction_floor_applied"] is False

    def test_escalate_action_emitted(self):
        res = score_graph([edge(CLEAN, SANCTIONED, 50)], [], sanctioned={SANCTIONED})
        assert any("ESCALATE IMMEDIATELY" in a
                   for a in res[SANCTIONED]["recommended_actions"])


class TestPatterns:
    def test_collection_funnel_detected(self):
        edges = [edge(v, COLLECTOR, 500, days_ago=10) for v in VICTIM]
        edges.append(edge(COLLECTOR, MULE, 14_000, days_ago=1))
        res = score_graph(edges, [COLLECTOR])
        c = res[COLLECTOR]
        assert any(f["code"] == "FUNNEL_ACCOUNT" for f in c["factors"])
        assert c["stats"]["fanIn"] == 30
        assert c["stats"]["fanOut"] == 1

    def test_pass_through_mule_detected(self):
        edges = [edge(COLLECTOR, MULE, 10_000, days_ago=2),
                 edge(MULE, EXCHANGE, 9_900, days_ago=1)]
        res = score_graph(edges, [])
        assert any(f["code"] == "PASS_THROUGH" for f in res[MULE]["factors"])

    def test_mixer_proximity_scores(self):
        edges = [edge(MULE, MIXER, 5_000)]
        res = score_graph(edges, [], mixers={MIXER})
        assert res[MULE]["hops_to_mixer"] == 1
        assert any(f["code"] == "MIXER_1HOP" for f in res[MULE]["factors"])

    def test_mixer_evidence_warning_emitted(self):
        res = score_graph([edge(MULE, MIXER, 5_000)], [], mixers={MIXER})
        assert any("preserve pre-mixer" in a.lower()
                   for a in res[MULE]["recommended_actions"])

    def test_peel_chain_depth(self):
        """Each hop forwards 70-98% — the peel signature."""
        chain = ["0xp%039x" % i for i in range(7)]
        edges, val = [], 10_000.0
        for i in range(6):
            val *= 0.92
            edges.append(edge(chain[i], chain[i + 1], val, days_ago=6 - i))
        res = score_graph(edges, [chain[0]])
        assert res[chain[0]]["peel_chain_depth"] >= 4
        assert any(f["code"] == "PEEL_CHAIN" for f in res[chain[0]]["factors"])

    def test_structuring_below_threshold(self):
        edges = [edge(f"0xs{i:039x}", COLLECTOR, 9_200 + i, days_ago=5)
                 for i in range(10)]
        res = score_graph(edges, [COLLECTOR])
        assert any(f["code"] == "STRUCTURING" for f in res[COLLECTOR]["factors"])

    def test_clean_wallet_scores_low(self):
        edges = [edge(CLEAN, "0xz" + "0"*39, 200, days_ago=100)]
        res = score_graph(edges, [])
        assert res[CLEAN]["risk_band"] == "low"
        assert res[CLEAN]["risk_score"] < 35


class TestExplainability:
    def test_every_factor_is_named_and_justified(self):
        res = score_graph([edge(CLEAN, SANCTIONED, 50)], [], sanctioned={SANCTIONED})
        for r in res.values():
            for f in r["factors"]:
                assert f["code"] and f["label"] and f["detail"]
                assert f["points"] > 0

    def test_points_sum_to_score_unless_floored_or_capped(self):
        edges = [edge(v, COLLECTOR, 500, days_ago=10) for v in VICTIM[:25]]
        res = score_graph(edges, [COLLECTOR])
        r = res[COLLECTOR]
        if not r["sanction_floor_applied"] and r["risk_score"] < 100:
            assert r["risk_score"] == pytest.approx(
                sum(f["points"] for f in r["factors"]), abs=0.05)

    def test_narrative_is_a_sentence(self):
        res = score_graph([edge(CLEAN, SANCTIONED, 50)], [], sanctioned={SANCTIONED})
        n = res[SANCTIONED]["narrative"]
        assert n.endswith(".") and "/100" in n and len(n) > 40

    def test_unscored_wallet_says_so_rather_than_inventing(self):
        res = score_graph([edge(CLEAN, "0xz" + "0"*39, 10, days_ago=200)], [])
        assert "No risk factor fired" in res[CLEAN]["narrative"]

    def test_every_wallet_gets_an_action(self):
        edges = [edge(v, COLLECTOR, 500) for v in VICTIM[:12]]
        res = score_graph(edges, [COLLECTOR])
        assert all(r["recommended_actions"] for r in res.values())


class TestVaspEndpoint:
    def test_direct_exchange_deposit_triggers_bnss_notice(self):
        edges = [edge(MULE, EXCHANGE, 9_000)]
        res = score_graph(edges, [MULE], exchanges={EXCHANGE})
        assert res[MULE]["hops_to_exchange"] == 1
        assert any("Section 91" in a or "notice" in a.lower()
                   for a in res[MULE]["recommended_actions"])

    def test_no_exchange_path_is_reported_honestly(self):
        res = score_graph([edge(CLEAN, MULE, 100)], [CLEAN])
        assert res[CLEAN]["hops_to_exchange"] is None
        assert any("No exchange endpoint traced" in a
                   for a in res[CLEAN]["recommended_actions"])


class TestValuationHonesty:
    def test_unvalued_transfers_are_counted_not_hidden(self):
        """A low USD figure must not be mistaken for low activity."""
        edges = [edge(CLEAN, MULE, 0.0, asset="SCAMCOIN", unvalued=True)
                 for _ in range(5)]
        res = score_graph(edges, [])
        assert res[MULE]["stats"]["unvaluedTransfers"] == 5
        assert res[MULE]["stats"]["inUsd"] == 0.0

    def test_assets_listed_per_wallet(self):
        edges = [edge(CLEAN, MULE, 100, asset="USDT"),
                 edge(CLEAN, MULE, 50, asset="USDC")]
        res = score_graph(edges, [])
        assert set(res[MULE]["stats"]["assets"]) == {"USDT", "USDC"}


class TestStats:
    def test_in_out_and_balance(self):
        edges = [edge(CLEAN, MULE, 1_000), edge(MULE, EXCHANGE, 400)]
        s = build_stats(edges)[f"eth:{MULE}"]
        assert s.in_usd == 1_000 and s.out_usd == 400
        assert s.balance_usd == 600
        assert s.pass_through_ratio == pytest.approx(0.4)
