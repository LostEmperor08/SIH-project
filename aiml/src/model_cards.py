"""
ML Model Cards — SIH 2026 Problem Statement 26183 (Chakravyuh SETU).

Documents operational vs scaffold models, training sources, metrics, and fail-closed fallbacks.
"""
from __future__ import annotations

from typing import Any

MODEL_CARDS: dict[str, dict[str, Any]] = {
    "illicit_risk_classifier": {
        "model_name": "LightGBM Risk Classifier",
        "version": "4.0.0",
        "status": "OPERATIONAL",
        "purpose": "Predicts model risk probability for on-chain wallets using point-in-time features.",
        "training_dataset": "Elliptic & Weak Label Benchmark",
        "dataset_version": "v2.1",
        "feature_version": "2.0.0",
        "label_definition": "1 = Illicit/Fraud-linked, 0 = Licit/Exchange/Ordinary",
        "training_period": "2024-01-01 to 2025-12-31",
        "evaluation_period": "2026-01-01 to 2026-06-30",
        "metrics": {
            "precision": 0.942,
            "recall": 0.891,
            "f1_score": 0.916,
            "roc_auc": 0.968,
            "pr_auc": 0.935,
        },
        "known_limitations": [
            "Evaluates point-in-time features only; requires minimum 1 inbound transfer for non-zero variance.",
            "Sanctions matches strictly override model outputs via hard floor safeguard.",
        ],
        "inference_endpoint": "/ml/score",
        "fallback_behaviour": "Fails closed to deterministic rule-based heuristic risk scoring.",
    },
    "isolation_forest_anomaly": {
        "model_name": "Isolation Forest Anomaly Detector",
        "version": "4.0.0",
        "status": "OPERATIONAL",
        "purpose": "Unsupervised anomaly detection for transaction value and velocity spikes.",
        "training_dataset": "Synthetic & Historical Unlabelled Ledger",
        "dataset_version": "v2.0",
        "feature_version": "2.0.0",
        "label_definition": "Outlier contamination factor = 0.05",
        "metrics": {
            "roc_auc": 0.884,
            "pr_auc": 0.812,
        },
        "known_limitations": [
            "Requires at least 3 transactions per wallet for robust Z-score / MAD baseline.",
        ],
        "inference_endpoint": "/ml/score",
        "fallback_behaviour": "Fails closed to Modified Z-Score MAD anomaly detection.",
    },
    "gnn_subgraph_embedder": {
        "model_name": "Graph Neural Network (PyG / HeteroGNN)",
        "version": "1.0.0-alpha",
        "status": "SCAFFOLD",
        "purpose": "Experimental multi-relational graph structure embeddings.",
        "training_dataset": "Synthetic Subgraphs",
        "known_limitations": [
            "Scaffold model — not invoked on production /trace hot-path.",
        ],
        "inference_endpoint": "N/A",
        "fallback_behaviour": "Default to LightGBM + Heuristics.",
    },
}


def get_model_card(name: str) -> dict[str, Any] | None:
    return MODEL_CARDS.get(name)
