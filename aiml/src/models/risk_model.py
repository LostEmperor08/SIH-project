"""
The production risk model — refactored.

WHAT CHANGED AND WHY
--------------------
The previous design had its own 37-feature schema in
`src/features/schema.py`, computed by `src/features/extract.py`. The gateway
then computed its OWN statistics in `backend/app/services/risk.py`. Two
definitions of "what the model sees" is the textbook training/serving skew:
the model scores well offline and produces nonsense in production because
the serving path built a column differently.

This model trains on the gateway's own output. `FEATURE_ORDER` lives in
`risk.py`, beside the code that computes it, and there is nothing to keep in
sync — the training rows ARE production rows.

It also learns from the right labels. Synthetic wallets were generated from
the same patterns the label functions detect, so accuracy was circular by
construction. Here the labels come from `ml_feedback` — real verdicts from
officers who worked the case.

WHAT THE MODEL IS FOR
---------------------
Not to replace the heuristic. The heuristic is auditable and always
available; the model learns where it is WRONG. `heuristic_score` is itself
an input feature, so the model is free to agree with it (and mostly will) or
to override it when the evidence says otherwise. That framing is what makes
a low-data model safe: with no training data it defers to the rules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

log = logging.getLogger("chakravyuh.ml.risk")

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:                                    # pragma: no cover
    HAS_LGB = False

from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.metrics import (
    average_precision_score, brier_score_loss, roc_auc_score,
)
from sklearn.preprocessing import RobustScaler

# The minimum labelled examples before a supervised model is allowed to
# exist at all. Below this it would produce confident nonsense, and
# confident nonsense is what gets the wrong person's assets frozen.
MIN_LABELS = 40
MIN_PER_CLASS = 12


@dataclass
class TrainReport:
    trained: bool
    reason: str = ""
    n_train: int = 0
    n_val: int = 0
    n_positive: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    feature_importance: list[tuple[str, float]] = field(default_factory=list)


class RiskModel:
    """
    Supervised refinement of the heuristic score.

    predict_proba() returns P(illicit). If the model was never trained (not
    enough labels yet), `is_trained` is False and callers fall back to the
    heuristic — the system degrades to something auditable rather than
    guessing.
    """

    def __init__(self, feature_order: list[str], **params):
        self.feature_order = list(feature_order)
        self.params = {
            "n_estimators": 400, "learning_rate": 0.05, "num_leaves": 31,
            "min_child_samples": 8, "subsample": 0.9, "subsample_freq": 1,
            "colsample_bytree": 0.9, "reg_lambda": 1.0,
            "random_state": 42, "n_jobs": -1, "verbose": -1, **params,
        }
        self.model: Any = None
        self.calibrated: Any = None
        self.threshold = 0.5
        self.is_trained = False
        self.report = TrainReport(trained=False, reason="not trained")

    # -----------------------------------------------------------------
    def _matrix(self, rows: list[dict[str, float]]) -> np.ndarray:
        """dicts -> array in FEATURE_ORDER. Missing keys are a hard error."""
        out = np.empty((len(rows), len(self.feature_order)), dtype=float)
        for i, r in enumerate(rows):
            for j, k in enumerate(self.feature_order):
                if k not in r:
                    raise KeyError(
                        f"feature '{k}' missing from row {i}. The feature "
                        "contract is FEATURE_ORDER in risk.py — regenerate "
                        "the training rows rather than patching here."
                    )
                out[i, j] = float(r[k])
        return out

    # -----------------------------------------------------------------
    def fit(self, rows: list[dict[str, float]], labels: list[int],
            sample_weight: list[float] | None = None) -> TrainReport:
        n = len(rows)
        y = np.asarray(labels, dtype=int)
        pos, neg = int(y.sum()), int(len(y) - y.sum())

        if n < MIN_LABELS:
            self.report = TrainReport(
                False,
                f"only {n} labelled wallets; need {MIN_LABELS}. Collect "
                "analyst verdicts via POST /ml/feedback — the heuristic "
                "remains in use until then.",
                n_train=n, n_positive=pos)
            return self.report

        if pos < MIN_PER_CLASS or neg < MIN_PER_CLASS:
            self.report = TrainReport(
                False,
                f"class imbalance too severe: {pos} illicit / {neg} licit "
                f"(need {MIN_PER_CLASS} of each).",
                n_train=n, n_positive=pos)
            return self.report

        X = self._matrix(rows)

        # Temporal-style split: last 20% held out. Rows arrive in trace
        # order, so this approximates "train on the past, test on the
        # future" — a random split leaks and inflates every metric.
        cut = int(n * 0.8)
        Xtr, Xva = X[:cut], X[cut:]
        ytr, yva = y[:cut], y[cut:]
        wtr = np.asarray(sample_weight[:cut]) if sample_weight else None

        if len(np.unique(ytr)) < 2 or len(np.unique(yva)) < 2:
            # fall back to fitting on everything; report honestly that the
            # held-out metrics are unavailable
            Xtr, ytr, wtr = X, y, (np.asarray(sample_weight) if sample_weight else None)
            Xva, yva = None, None

        spw = neg / max(pos, 1)
        if HAS_LGB:
            base = lgb.LGBMClassifier(scale_pos_weight=spw, **self.params)
        else:                                          # pragma: no cover
            base = GradientBoostingClassifier(random_state=42)
        base.fit(Xtr, ytr, sample_weight=wtr)
        self.model = base

        # Calibration matters more than raw ranking here: the output drives
        # a risk BAND, and an uncalibrated 0.9 that means 0.4 is worse than
        # no score. Sigmoid handles small samples better than isotonic.
        try:
            cv = min(3, int(min(np.bincount(ytr))))
            if cv >= 2:
                self.calibrated = CalibratedClassifierCV(
                    base, method="sigmoid", cv=cv)
                self.calibrated.fit(Xtr, ytr)
        except Exception as e:                         # noqa: BLE001
            log.warning("calibration skipped: %s", e)
            self.calibrated = None

        metrics: dict[str, Any] = {}
        if Xva is not None and len(Xva):
            p = self._raw_proba(Xva)
            metrics = {
                "auc_pr": float(average_precision_score(yva, p)),
                "roc_auc": float(roc_auc_score(yva, p)),
                # Brier score measures calibration, not ranking. Lower is
                # better; 0.25 is what you get predicting 0.5 for everything.
                "brier": float(brier_score_loss(yva, p)),
                "base_rate": float(yva.mean()),
                "n_val": int(len(yva)),
            }
            self.threshold = self._tune_threshold(yva, p)
            metrics["threshold"] = self.threshold

        imp = []
        raw_imp = getattr(base, "feature_importances_", None)
        if raw_imp is not None:
            imp = sorted(zip(self.feature_order, (float(v) for v in raw_imp)),
                         key=lambda kv: -kv[1])[:12]

        self.is_trained = True
        self.report = TrainReport(
            True, "ok", n_train=len(Xtr), n_val=len(Xva) if Xva is not None else 0,
            n_positive=pos, metrics=metrics, feature_importance=imp)
        return self.report

    @staticmethod
    def _tune_threshold(y: np.ndarray, p: np.ndarray) -> float:
        """Pick the F1-optimal threshold. 0.5 is arbitrary at a low base rate."""
        from sklearn.metrics import precision_recall_curve
        prec, rec, thr = precision_recall_curve(y, p)
        if not len(thr):
            return 0.5
        f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
        return float(thr[int(np.nanargmax(f1[:-1]))])

    def _raw_proba(self, X: np.ndarray) -> np.ndarray:
        est = self.calibrated or self.model
        return est.predict_proba(X)[:, 1]

    # -----------------------------------------------------------------
    def predict_proba(self, rows: list[dict[str, float]]) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError(
                "RiskModel is not trained. Callers must check is_trained and "
                "fall back to the heuristic score."
            )
        return self._raw_proba(self._matrix(rows))

    def blend(self, rows: list[dict[str, float]],
              heuristic_scores: list[float], model_weight: float = 0.4,
              ) -> list[dict[str, Any]]:
        """
        Combine heuristic and model into a final 0-100 score.

        The heuristic keeps the majority weight by default. It is auditable,
        an officer can verify it by hand, and it does not silently drift. The
        model is a refinement, not a replacement — and until it has earned
        trust on real cases, weighting it above the rules would be a claim
        the evidence does not support.
        """
        if not self.is_trained:
            return [{"risk_score": round(h, 2), "model_used": False,
                     "illicit_probability": None} for h in heuristic_scores]

        probs = self.predict_proba(rows)
        out = []
        for h, p in zip(heuristic_scores, probs):
            blended = (1 - model_weight) * h + model_weight * (p * 100.0)
            out.append({
                "risk_score": round(float(np.clip(blended, 0, 100)), 2),
                "illicit_probability": round(float(p), 4),
                "model_used": True,
                "model_weight": model_weight,
                "heuristic_score": round(h, 2),
            })
        return out


# =====================================================================
class AnomalyModel:
    """
    Unsupervised outlier detection — the net for what supervision cannot
    catch, because the campaign started last week and nobody has labelled it.

    Needs no labels at all, so it works from day one. RobustScaler rather
    than StandardScaler: crypto values are heavy-tailed and a handful of
    whale transfers would otherwise dominate every scaled feature.
    """

    def __init__(self, feature_order: list[str], contamination: float = 0.05):
        self.feature_order = list(feature_order)
        self.contamination = contamination
        self.scaler = RobustScaler()
        self.model: Any = None
        self.is_trained = False
        self._lo = self._hi = 0.0

    def fit(self, rows: list[dict[str, float]]) -> dict[str, Any]:
        if len(rows) < 30:
            return {"trained": False,
                    "reason": f"only {len(rows)} wallets; need 30+"}
        X = np.array([[r[k] for k in self.feature_order] for r in rows], dtype=float)
        Xs = self.scaler.fit_transform(X)
        self.model = IsolationForest(
            n_estimators=200, contamination=self.contamination,
            max_samples=min(256, len(rows)), random_state=42, n_jobs=-1).fit(Xs)
        raw = self.model.score_samples(Xs)
        self._lo, self._hi = float(raw.min()), float(raw.max())
        self.is_trained = True
        return {"trained": True, "n": len(rows),
                "mean_score": float(self.anomaly_score(rows).mean())}

    def anomaly_score(self, rows: list[dict[str, float]]) -> np.ndarray:
        """0 = typical, 1 = maximally anomalous."""
        if not self.is_trained:
            return np.zeros(len(rows))
        X = np.array([[r[k] for k in self.feature_order] for r in rows], dtype=float)
        raw = self.model.score_samples(self.scaler.transform(X))
        span = max(self._hi - self._lo, 1e-9)
        return np.clip(1.0 - (raw - self._lo) / span, 0.0, 1.0)
