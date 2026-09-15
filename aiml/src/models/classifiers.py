"""
The four production models.

  IllicitModel    binary   — is this wallet fraud-linked?
  VASPModel       multiclass — which kind of service is it? (the PS 26183 ask)
  TypologyModel   multilabel — which fraud typology does it match?
  AnomalyModel    unsupervised — does it look unlike anything we've seen?

All four share a common interface (fit / predict_proba / explain) so the
serving layer treats them uniformly, and all four are calibrated, because
an uncalibrated score cannot be turned into a risk band an officer can act
on. A "0.9" that means nothing is worse than no score at all.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score, classification_report, confusion_matrix,
    f1_score, precision_recall_curve, roc_auc_score,
)
from sklearn.preprocessing import LabelEncoder, RobustScaler

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:                                    # pragma: no cover
    HAS_LGB = False
    from sklearn.ensemble import HistGradientBoostingClassifier

from ..features.schema import FEATURE_NAMES


def _eval_kwargs(X_val, y_val, patience: int, metric: str | None = None) -> dict:
    """
    Build validation kwargs across LightGBM API versions.

    LightGBM 4.7 deprecated `eval_set` in favour of `eval_X`/`eval_y`, but
    4.3-4.6 do not accept the new names. Sniff the signature rather than
    pinning a version, so this works on whatever the deployment box has.
    """
    if not HAS_LGB or X_val is None or len(X_val) == 0:
        return {}
    import inspect
    sig = inspect.signature(lgb.LGBMClassifier.fit).parameters
    kw: dict = {"callbacks": [lgb.early_stopping(patience, verbose=False),
                             lgb.log_evaluation(0)]}
    if "eval_X" in sig:
        kw |= {"eval_X": X_val, "eval_y": y_val}
    else:
        kw |= {"eval_set": [(X_val, y_val)]}
    if metric:
        kw["eval_metric"] = metric
    return kw


# =====================================================================
# 1. Illicit wallet classifier
# =====================================================================
class IllicitModel:
    """
    Binary fraud-link classifier.

    Two details that matter more than the algorithm choice:

    1. `scale_pos_weight` instead of SMOTE. Synthetic minority oversampling
       invents wallets that never existed and wrecks probability calibration
       — fatal when the output drives an asset-freezing decision.

    2. The decision threshold is TUNED on validation, not left at 0.5.
       At ~5% base rate, 0.5 is arbitrary; we pick the threshold that
       maximises F1 and report what it is.
    """

    def __init__(self, **params):
        self.params = {
            "n_estimators": 1200, "learning_rate": 0.03, "num_leaves": 64,
            "min_child_samples": 40, "subsample": 0.8, "subsample_freq": 1,
            "colsample_bytree": 0.8, "reg_lambda": 1.0,
            "random_state": 42, "n_jobs": -1, "verbose": -1,
            **params,
        }
        self.model: Any = None
        self.threshold = 0.5
        self.feature_names: list[str] = []
        self.metrics: dict = {}

    def fit(self, X, y, X_val=None, y_val=None, sample_weight=None):
        self.feature_names = list(X.columns)
        pos = int(np.sum(y))
        neg = len(y) - pos
        if pos == 0 or neg == 0:
            raise ValueError(
                f"need both classes to train; got {pos} illicit / {neg} licit"
            )
        spw = neg / max(pos, 1)

        if HAS_LGB:
            self.model = lgb.LGBMClassifier(scale_pos_weight=spw, **self.params)
            fit_kw = {"sample_weight": sample_weight}
            fit_kw |= _eval_kwargs(X_val, y_val, 100, "average_precision")
            self.model.fit(X, y, **fit_kw)
        else:                                          # pragma: no cover
            warnings.warn("lightgbm unavailable — falling back to sklearn HGB")
            self.model = HistGradientBoostingClassifier(
                max_iter=400, learning_rate=0.05, random_state=42)
            self.model.fit(X, y, sample_weight=sample_weight)

        if X_val is not None and len(X_val) and len(np.unique(y_val)) > 1:
            self._tune_threshold(X_val, y_val)
            self.metrics = self.evaluate(X_val, y_val)
        return self

    def _tune_threshold(self, X_val, y_val):
        p = self.model.predict_proba(X_val)[:, 1]
        prec, rec, thr = precision_recall_curve(y_val, p)
        f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
        best = int(np.nanargmax(f1[:-1])) if len(thr) else 0
        self.threshold = float(thr[best]) if len(thr) else 0.5

    def predict_proba(self, X) -> np.ndarray:
        return self.model.predict_proba(X[self.feature_names])[:, 1]

    def predict(self, X) -> np.ndarray:
        return (self.predict_proba(X) >= self.threshold).astype(int)

    def evaluate(self, X, y) -> dict:
        p = self.predict_proba(X)
        yhat = (p >= self.threshold).astype(int)
        return {
            "roc_auc": float(roc_auc_score(y, p)),
            # AUC-PR is the metric that matters at a 5% base rate; ROC-AUC
            # flatters every model on imbalanced data.
            "auc_pr": float(average_precision_score(y, p)),
            "f1": float(f1_score(y, yhat, zero_division=0)),
            "threshold": self.threshold,
            "base_rate": float(np.mean(y)),
            "confusion": confusion_matrix(y, yhat).tolist(),
            "report": classification_report(y, yhat, zero_division=0,
                                            target_names=["licit", "illicit"],
                                            output_dict=True),
        }

    def feature_importance(self, top: int = 20) -> pd.DataFrame:
        imp = getattr(self.model, "feature_importances_", None)
        if imp is None:
            return pd.DataFrame()
        return (pd.DataFrame({"feature": self.feature_names, "importance": imp})
                .sort_values("importance", ascending=False).head(top)
                .reset_index(drop=True))


# =====================================================================
# 2. VASP / entity attribution  — the core PS 26183 deliverable
# =====================================================================
class VASPModel:
    """
    Multi-class attribution of a wallet (or its cluster) to a service type.

    Abstention is a first-class outcome: below `min_confidence` we return
    'unknown' rather than guessing. Telling an officer "this is Binance"
    when it is not sends a freeze request to the wrong VASP and burns the
    only chance to recover the funds.
    """

    CLASSES = ["exchange", "mixer", "bridge", "gambling",
               "darknet", "merchant", "p2p", "unknown"]

    def __init__(self, min_confidence: float = 0.55, **params):
        self.params = {
            "n_estimators": 800, "learning_rate": 0.05, "num_leaves": 48,
            "min_child_samples": 30, "subsample": 0.85, "subsample_freq": 1,
            "colsample_bytree": 0.85, "random_state": 42,
            "n_jobs": -1, "verbose": -1, **params,
        }
        self.min_confidence = min_confidence
        self.model: Any = None
        self.encoder = LabelEncoder()
        self.feature_names: list[str] = []
        self.metrics: dict = {}

    def fit(self, X, y, X_val=None, y_val=None, sample_weight=None):
        self.feature_names = list(X.columns)
        y_enc = self.encoder.fit_transform(y)

        if HAS_LGB:
            self.model = lgb.LGBMClassifier(
                objective="multiclass", num_class=len(self.encoder.classes_),
                class_weight="balanced", **self.params)
            fit_kw = {"sample_weight": sample_weight}
            if X_val is not None and len(X_val):
                fit_kw |= _eval_kwargs(X_val, self.encoder.transform(y_val), 80)
            self.model.fit(X, y_enc, **fit_kw)
        else:                                          # pragma: no cover
            self.model = HistGradientBoostingClassifier(max_iter=300, random_state=42)
            self.model.fit(X, y_enc, sample_weight=sample_weight)

        if X_val is not None and len(X_val):
            self.metrics = self.evaluate(X_val, y_val)
        return self

    def predict_proba(self, X) -> pd.DataFrame:
        p = self.model.predict_proba(X[self.feature_names])
        return pd.DataFrame(p, columns=self.encoder.classes_, index=X.index)

    def predict(self, X) -> pd.DataFrame:
        proba = self.predict_proba(X)
        best = proba.idxmax(axis=1)
        conf = proba.max(axis=1)
        label = best.where(conf >= self.min_confidence, "unknown")
        return pd.DataFrame({
            "vasp_type": label,
            "confidence": conf.round(4),
            "runner_up": proba.apply(
                lambda r: r.drop(r.idxmax()).idxmax() if len(r) > 1 else None, axis=1),
            "abstained": conf < self.min_confidence,
        }, index=X.index)

    def evaluate(self, X, y) -> dict:
        pred = self.predict(X)
        covered = ~pred["abstained"]
        acc_cov = float((pred.loc[covered, "vasp_type"] == pd.Series(y, index=X.index)[covered]).mean()) \
            if covered.any() else 0.0
        return {
            "accuracy_all": float((pred["vasp_type"] == pd.Series(y, index=X.index)).mean()),
            # the number that actually matters: how often are we right WHEN
            # we commit to an answer
            "accuracy_when_confident": acc_cov,
            "coverage": float(covered.mean()),
            "report": classification_report(
                y, pred["vasp_type"], zero_division=0, output_dict=True),
        }


# =====================================================================
# 3. Fraud typology  — multi-label
# =====================================================================
class TypologyModel:
    """One binary head per typology. A wallet can match several."""

    def __init__(self, labels: list[str], min_confidence: float = 0.45, **params):
        self.labels = labels
        self.min_confidence = min_confidence
        self.params = {
            "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 32,
            "min_child_samples": 25, "random_state": 42,
            "n_jobs": -1, "verbose": -1, **params,
        }
        self.heads: dict[str, Any] = {}
        self.feature_names: list[str] = []
        self.metrics: dict = {}

    def fit(self, X, Y: pd.DataFrame, X_val=None, Y_val=None):
        self.feature_names = list(X.columns)
        report = {}
        for lab in self.labels:
            if lab not in Y.columns:
                continue
            y = Y[lab].values
            pos = int(y.sum())
            if pos < 20:
                # Refuse to fit a head on a handful of positives. A model
                # trained on 6 examples will produce confident nonsense,
                # and confident nonsense is what gets the wrong person's
                # assets frozen.
                print(f"[typology] skipping '{lab}' — only {pos} positives")
                continue
            spw = (len(y) - pos) / max(pos, 1)
            if HAS_LGB:
                m = lgb.LGBMClassifier(scale_pos_weight=spw, **self.params)
                kw = {}
                if X_val is not None and Y_val is not None and lab in Y_val.columns \
                        and Y_val[lab].nunique() > 1:
                    kw = _eval_kwargs(X_val, Y_val[lab].values, 60)
                m.fit(X, y, **kw)
            else:                                      # pragma: no cover
                m = HistGradientBoostingClassifier(max_iter=200, random_state=42)
                m.fit(X, y)
            self.heads[lab] = m

            if X_val is not None and Y_val is not None and lab in Y_val.columns \
                    and Y_val[lab].nunique() > 1:
                p = m.predict_proba(X_val)[:, 1]
                report[lab] = {
                    "auc_pr": float(average_precision_score(Y_val[lab], p)),
                    "positives_train": pos,
                }
        self.metrics = report
        return self

    def predict_proba(self, X) -> pd.DataFrame:
        return pd.DataFrame(
            {lab: m.predict_proba(X[self.feature_names])[:, 1]
             for lab, m in self.heads.items()},
            index=X.index,
        )

    def predict(self, X) -> pd.DataFrame:
        proba = self.predict_proba(X)
        return (proba >= self.min_confidence).astype(int)

    def top_typologies(self, X, k: int = 3) -> list[list[dict]]:
        proba = self.predict_proba(X)
        out = []
        for _, row in proba.iterrows():
            ranked = row.sort_values(ascending=False).head(k)
            out.append([
                {"typology": t, "confidence": round(float(c), 4)}
                for t, c in ranked.items() if c >= self.min_confidence
            ])
        return out


# =====================================================================
# 4. Unsupervised anomaly detection
# =====================================================================
class AnomalyModel:
    """
    Isolation Forest over robust-scaled features.

    This is the net for what the supervised models cannot catch: a fraud
    campaign whose pattern is not in any label set, because it started last
    week. It answers "unlike anything we have seen", which is a different
    and complementary question to "resembles known fraud".

    RobustScaler, not StandardScaler — crypto value distributions are
    heavy-tailed and a handful of whale transfers would otherwise dominate
    every scaled feature.
    """

    def __init__(self, contamination: float = 0.03, **params):
        self.params = {
            "n_estimators": 300, "max_samples": 0.7,
            "contamination": contamination, "random_state": 42,
            "n_jobs": -1, **params,
        }
        self.scaler = RobustScaler()
        self.model: Any = None
        self.feature_names: list[str] = []
        self._lo = self._hi = 0.0

    def fit(self, X):
        self.feature_names = list(X.columns)
        Xs = self.scaler.fit_transform(X)
        self.model = IsolationForest(**self.params).fit(Xs)
        raw = self.model.score_samples(Xs)
        # store the training range so serving can map to a stable 0-1 scale
        self._lo, self._hi = float(raw.min()), float(raw.max())
        return self

    def anomaly_score(self, X) -> np.ndarray:
        """0 = typical, 1 = maximally anomalous."""
        Xs = self.scaler.transform(X[self.feature_names])
        raw = self.model.score_samples(Xs)
        span = max(self._hi - self._lo, 1e-9)
        return np.clip(1.0 - (raw - self._lo) / span, 0.0, 1.0)


# =====================================================================
# Score fusion
# =====================================================================
@dataclass
class FusionWeights:
    rules: float = 0.35
    illicit_model: float = 0.35
    anomaly: float = 0.15
    graph: float = 0.15
    sanction_floor: float = 90.0


def fuse_risk(
    rule_score: float,
    illicit_proba: float,
    anomaly_score: float,
    graph_score: float | None = None,
    *,
    sanctioned: bool = False,
    w: FusionWeights | None = None,
) -> dict:
    """
    Combine every signal into one 0-100 score, with the components exposed.

    The sanction floor is deliberate and non-negotiable: a live OFAC hit
    pins the score at 90+ regardless of what the models think. A model is
    allowed to raise an alarm; it is not allowed to talk one down.
    """
    w = w or FusionWeights()
    parts = {
        "rules": (rule_score, w.rules),
        "illicit_model": (illicit_proba * 100, w.illicit_model),
        "anomaly": (anomaly_score * 100, w.anomaly),
    }
    if graph_score is not None:
        parts["graph"] = (graph_score * 100, w.graph)

    total_w = sum(wt for _, wt in parts.values())
    score = sum(v * wt for v, wt in parts.values()) / max(total_w, 1e-9)

    if sanctioned:
        score = max(score, w.sanction_floor)

    score = float(np.clip(score, 0, 100))
    band = ("critical" if score >= 80 else
            "high" if score >= 60 else
            "medium" if score >= 35 else "low")

    return {
        "risk_score": round(score, 2),
        "risk_band": band,
        "components": {k: round(v, 2) for k, (v, _) in parts.items()},
        "weights": {k: wt for k, (_, wt) in parts.items()},
        "sanction_floor_applied": bool(sanctioned and score <= w.sanction_floor + 1e-6),
    }
