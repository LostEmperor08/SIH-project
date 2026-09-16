"""
Prove a trace is reproducible, and time it.

    cd backend && python3 ../scripts/determinism_check.py 0xYourAddress polygon

Runs the same trace twice and compares. The second run should be far
faster (cached upstream payloads) and return an IDENTICAL node count.
Different counts across two runs means an address was refused mid-trace --
which the output now names instead of hiding.

Run this from your own terminal. A restricted network (a corporate proxy,
a sandbox) returns 403 from Etherscan and every run will report
complete=False with zero nodes -- that is the network, not the tracer.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")
except ImportError:
    pass

from app.config import Settings                      # noqa: E402
from app.schemas import Target                       # noqa: E402
from app.services.trace import build_graph, trace_multi_hop   # noqa: E402


async def one(cfg, targets, label):
    t0 = time.perf_counter()
    tr = await trace_multi_hop(targets, 2, cfg.default_cap_per_address, cfg)
    g = build_graph(tr, targets)
    print(f"{label}: {time.perf_counter() - t0:6.1f}s  "
          f"nodes={len(g['nodes']):4d}  edges={len(g['edges']):4d}  "
          f"complete={tr.complete}  unreachable={len(tr.dropped)}  "
          f"requests={tr.upstream.get('requests')}  "
          f"cached={tr.upstream.get('cache_hits')}  "
          f"rate-limit retries={tr.upstream.get('rate_limit_retries')}")
    for e in tr.errors[:3]:
        print(f"        {e}")
    return len(g["nodes"])


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    address, chain = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "polygon")
    cfg = Settings()
    targets = [Target(chain=chain, address=address)]

    print(f"tracing {address} on {chain}, 2 hops\n"
          f"paced at {cfg.etherscan_rps}/s, cache {cfg.provider_cache_seconds}s\n")
    a = await one(cfg, targets, "run 1")
    b = await one(cfg, targets, "run 2")

    print()
    if a == b:
        print(f"REPRODUCIBLE — both runs returned {a} nodes.")
        return 0
    print(f"NOT REPRODUCIBLE — {a} nodes then {b}. Check 'unreachable' above: "
          f"an address the provider refused is a branch that went missing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
