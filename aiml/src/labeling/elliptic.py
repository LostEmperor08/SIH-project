"""
Elliptic++ loader — the public pretraining corpus.

Elliptic++ (Bitcoin) ships two graphs; we use the ACTORS one, because our
unit of analysis is the wallet address, same as PS 26183:

  wallets_features.csv   822,942 addresses, 56 features, 49 time steps
  wallets_classes.csv    class 1 = illicit (14,266)
                         class 2 = licit   (251,088)
                         class 3 = unknown (557,588)
  AddrAddr_edgelist.csv  address -> address graph

Download (repo: https://github.com/git-disl/EllipticPlusPlus) and place the
CSVs under `data/elliptic++/`.

Two important honesty notes that belong in your report:

1.  Elliptic's 56 wallet features are ANONYMISED and standardised. They do
    not map onto our named features. So we do NOT concatenate the two
    feature spaces -- that would be meaningless. Instead we train a
    *separate* Elliptic-native model and use it as (a) a published benchmark
    to quote, and (b) a source of transferable structure via the shared
    graph topology features we can recompute from AddrAddr_edgelist.

2.  The illicit class is only ~5% of labelled nodes and ~1.7% of all nodes.
    Any accuracy figure quoted on this dataset without a class breakdown is
    meaningless -- predicting "all licit" scores 94.6%. Report precision,
    recall and AUC-PR, never accuracy alone.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from ..features.extract import Edge, _compute

ILLICIT, LICIT, UNKNOWN = 1, 2, 3


def _resolve(root: Path, *candidates: str) -> Path | None:
    for c in candidates:
        for p in (root / c, root / "Actors" / c, root / "wallets" / c, root / "Wallets" / c):
            if p.exists():
                return p
    return None


def load_wallets(
    root: str | Path,
    *,
    drop_unknown: bool = True,
    recompute_topology: bool = True,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    Returns (X, y, time_step).

    y is 1 for illicit, 0 for licit.  `time_step` is returned separately
    because the split MUST be temporal (see train.py) -- Elliptic's own
    paper shows a random split inflates F1 by a wide margin, and a model
    validated that way collapses the moment a new fraud campaign appears.
    """
    root = Path(root)
    f_feat = _resolve(root, "wallets_features.csv")
    f_cls = _resolve(root, "wallets_classes.csv")

    if f_feat is None or f_cls is None:
        raise FileNotFoundError(
            f"Elliptic++ wallet CSVs not found under {root}.\n"
            "Clone https://github.com/git-disl/EllipticPlusPlus and copy the "
            "Actors dataset CSVs into that folder."
        )

    feats = pd.read_csv(f_feat)
    classes = pd.read_csv(f_cls)

    key = "address" if "address" in feats.columns else feats.columns[0]
    cls_key = "address" if "address" in classes.columns else classes.columns[0]
    cls_val = "class" if "class" in classes.columns else classes.columns[-1]

    df = feats.merge(
        classes.rename(columns={cls_key: key, cls_val: "class"}),
        on=key, how="left",
    )
    df["class"] = pd.to_numeric(df["class"], errors="coerce").fillna(UNKNOWN).astype(int)

    if drop_unknown:
        before = len(df)
        df = df[df["class"] != UNKNOWN].copy()
        print(f"[elliptic] dropped {before - len(df):,} unlabelled nodes, "
              f"{len(df):,} remain")

    ts_col = next((c for c in ("Time step", "time_step", "timestep", "ts")
                   if c in df.columns), None)
    if ts_col is None:
        warnings.warn("no time-step column found; falling back to a single step")
        df["__ts"] = 1
        ts_col = "__ts"

    time_step = df[ts_col].astype(int).reset_index(drop=True)
    y = (df["class"] == ILLICIT).astype(int).reset_index(drop=True)

    drop = {key, "class", ts_col}
    X = df.drop(columns=[c for c in drop if c in df.columns]).reset_index(drop=True)
    X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0)

    if recompute_topology:
        topo = _topology_from_edgelist(root, df[key].tolist())
        if topo is not None:
            X = pd.concat([X, topo.reset_index(drop=True)], axis=1)
            print(f"[elliptic] added {topo.shape[1]} recomputed topology features")

    print(f"[elliptic] X={X.shape}  illicit={int(y.sum()):,} "
          f"({y.mean():.2%})  time steps={time_step.nunique()}")
    return X, y, time_step


def _topology_from_edgelist(root: Path, addresses: list[str]) -> pd.DataFrame | None:
    """
    Recompute OUR topology features from Elliptic's address-address graph.

    This is the bridge between the two feature spaces: Elliptic's 56 columns
    are anonymised, but the graph is real, so degree, entropy and fan ratios
    computed here mean the same thing as they do on our live Supabase graph.
    Those shared columns are what actually transfers.
    """
    f_edges = _resolve(root, "AddrAddr_edgelist.csv")
    if f_edges is None:
        warnings.warn("AddrAddr_edgelist.csv not found; skipping topology recompute")
        return None

    e = pd.read_csv(f_edges)
    src, dst = e.columns[0], e.columns[1]

    edges = [Edge(str(a), str(b), 1.0, float(i))
             for i, (a, b) in enumerate(zip(e[src], e[dst]))]

    feat = _compute(edges, [str(a) for a in addresses])
    keep = ["fan_in", "fan_out", "fan_ratio", "counterparty_entropy",
            "unique_cp_ratio", "degree_centrality", "reciprocity", "tx_count"]
    return feat[keep].add_prefix("topo_")


def load_transactions(root: str | Path, drop_unknown: bool = True):
    """The transaction-level graph — 203,769 nodes, 183 features."""
    root = Path(root)
    f_feat = _resolve(root, "txs_features.csv")
    f_cls = _resolve(root, "txs_classes.csv")
    if f_feat is None or f_cls is None:
        raise FileNotFoundError(f"Elliptic++ transaction CSVs not found under {root}")

    feats = pd.read_csv(f_feat)
    classes = pd.read_csv(f_cls)
    key = feats.columns[0]
    df = feats.merge(classes.rename(columns={classes.columns[0]: key}), on=key, how="left")
    cls = pd.to_numeric(df[df.columns[-1]], errors="coerce").fillna(UNKNOWN).astype(int)
    if drop_unknown:
        mask = cls != UNKNOWN
        df, cls = df[mask], cls[mask]
    ts = df[df.columns[1]].astype(int).reset_index(drop=True)
    y = (cls == ILLICIT).astype(int).reset_index(drop=True)
    X = df.drop(columns=[key, df.columns[-1]]).reset_index(drop=True)
    return X.apply(pd.to_numeric, errors="coerce").fillna(0.0), y, ts
