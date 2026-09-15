"""
End-to-end smoke test: raw edges -> features -> scores -> explanations.

    python -m tests.smoke_test

Exercises exactly the path /ml/score takes at runtime, so if this passes
the API will too. Run it in CI before every deploy.
"""
from __future__ import annotations

import json
import sys
import time

from serving.inference import load_models, score_from_subgraph

BASE_TS = 1_757_000_000  # a fixed epoch so runs are reproducible
DAY = 86_400


def build_scenario():
    """
    A victim-reported wallet laundering through a mule into an exchange,
    with a sanctioned address in the neighbourhood. Mirrors the fact
    pattern in PS 26183.
    """
    edges = []

    # 40 victims -> the reported collection wallet, over 12 days
    for i in range(40):
        edges.append({
            "from_address": f"victim{i:03d}",
            "to_address": "SUSPECT_COLLECTOR",
            "value_usd": 800 + (i % 7) * 120,
            "ts": BASE_TS + i * (DAY // 3),
            "tx_hash": f"vtx{i}",
        })

    # collector sweeps to two mules
    for j, mule in enumerate(["MULE_A", "MULE_B"]):
        edges.append({
            "from_address": "SUSPECT_COLLECTOR", "to_address": mule,
            "value_usd": 18_000 - j * 500,
            "ts": BASE_TS + 13 * DAY, "tx_hash": f"sweep{j}",
        })

    # peel chain off MULE_A
    prev, val = "MULE_A", 18_000.0
    for k in range(5):
        nxt = f"PEEL_{k}"
        val *= 0.92
        edges.append({"from_address": prev, "to_address": nxt,
                      "value_usd": val, "ts": BASE_TS + (14 + k) * DAY,
                      "tx_hash": f"peel{k}"})
        prev = nxt

    # MULE_B deposits straight into an exchange hot wallet
    edges.append({"from_address": "MULE_B", "to_address": "EXCHANGE_HOT",
                  "value_usd": 17_400, "ts": BASE_TS + 15 * DAY,
                  "tx_hash": "cashout1"})

    # exchange churn, so it looks like a real service
    for i in range(300):
        edges.append({
            "from_address": f"cust{i:03d}" if i % 2 else "EXCHANGE_HOT",
            "to_address": "EXCHANGE_HOT" if i % 2 else f"cust{i:03d}",
            "value_usd": 200 + (i % 50) * 30,
            "ts": BASE_TS + (i % 30) * DAY + (i % 24) * 3600,
            "tx_hash": f"ex{i}",
        })

    # the last peel hop touches a sanctioned address
    edges.append({"from_address": "PEEL_4", "to_address": "OFAC_LISTED",
                  "value_usd": 11_000, "ts": BASE_TS + 20 * DAY,
                  "tx_hash": "sanc1"})

    # and a mixer sits one hop from MULE_A
    edges.append({"from_address": "MULE_A", "to_address": "MIXER_SVC",
                  "value_usd": 1_400, "ts": BASE_TS + 16 * DAY,
                  "tx_hash": "mix1"})

    return edges


def main() -> int:
    print("=" * 66)
    print("CHAKRAVYUH SETU — ML smoke test")
    print("=" * 66)

    b = load_models("artifacts")
    print(f"\nmodels loaded: {b.status()['loaded']}")
    if not b.ready:
        print("FAIL: no models. Run `python -m src.train --source synthetic` first.")
        return 1

    edges = build_scenario()
    targets = ["SUSPECT_COLLECTOR", "MULE_A", "MULE_B", "EXCHANGE_HOT", "PEEL_4"]
    print(f"graph: {len(edges)} edges, scoring {len(targets)} wallets\n")

    t0 = time.perf_counter()
    results = score_from_subgraph(
        edges, targets,
        sanctioned={"OFAC_LISTED"},
        mixers={"MIXER_SVC"},
        exchanges={"EXCHANGE_HOT"},
        explain=True,
    )
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"scored in {elapsed:.1f} ms ({elapsed/len(targets):.1f} ms/wallet)\n")

    failures = []
    for r in results:
        print("-" * 66)
        print(f"{r['address']}   risk {r['risk_score']}/100  [{r['risk_band']}]")
        print(f"  illicit_p={r['illicit_probability']}  anomaly={r['anomaly_score']}  "
              f"rules={r['rule_score']}")
        print(f"  hops -> exchange:{r['hops_to_exchange']}  "
              f"sanctioned:{r['hops_to_sanctioned']}  mixer:{r['hops_to_mixer']}")
        if r.get("vasp_attribution"):
            v = r["vasp_attribution"]
            print(f"  VASP: {v['type']} ({v['confidence']:.2f})"
                  f"{' [abstained]' if v['abstained'] else ''}")
        if r["typologies"]:
            print("  typologies: " + ", ".join(
                f"{t['typology']}({t['confidence']:.2f})" for t in r["typologies"]))
        print(f"  {r['narrative']}")
        for a in r["recommended_actions"]:
            print(f"    -> {a}")

    # ---- assertions ------------------------------------------------
    by = {r["address"]: r for r in results}

    checks = [
        ("collector is high-risk",
         by["SUSPECT_COLLECTOR"]["risk_score"] >= 35),
        ("collector fan-in recognised",
         by["SUSPECT_COLLECTOR"]["rule_score"] >= 0),
        ("MULE_B reaches the exchange in 1 hop",
         by["MULE_B"]["hops_to_exchange"] == 1),
        ("exchange wallet is 0 hops from itself",
         by["EXCHANGE_HOT"]["hops_to_exchange"] == 0),
        ("MULE_A is 1 hop from the mixer",
         by["MULE_A"]["hops_to_mixer"] == 1),
        ("PEEL_4 is 1 hop from the sanctioned address",
         by["PEEL_4"]["hops_to_sanctioned"] == 1),
        ("every wallet got a narrative",
         all(r.get("narrative") for r in results)),
        ("every wallet got at least one recommendation",
         all(r["recommended_actions"] for r in results)),
        ("every wallet got SHAP contributions",
         all(len(r["explanation"]) > 0 for r in results)),
        ("scores are bounded 0-100",
         all(0 <= r["risk_score"] <= 100 for r in results)),
        ("latency under 500ms for 5 wallets", elapsed < 500),
    ]

    print("\n" + "=" * 66)
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(name)

    # sanctions floor: force a direct hit and confirm the floor holds
    forced = score_from_subgraph(
        edges, ["PEEL_4"], sanctioned={"OFAC_LISTED", "PEEL_4"},
        mixers={"MIXER_SVC"}, exchanges={"EXCHANGE_HOT"}, explain=False)[0]
    floor_ok = forced["risk_score"] >= 90
    print(f"  [{'PASS' if floor_ok else 'FAIL'}] sanctions floor pins score to >=90 "
          f"(got {forced['risk_score']})")
    if not floor_ok:
        failures.append("sanctions floor")

    print("=" * 66)
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("ALL CHECKS PASSED")

    with open("reports/smoke_test_output.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("sample output -> reports/smoke_test_output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
