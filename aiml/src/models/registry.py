"""
Model registry — versioned save/load with a manifest.

An investigation platform must be able to answer "which model version
produced this score, trained on what, when?" months later, in court. A
bare .pkl cannot answer that. Every artifact here carries a manifest with
the feature list, training metrics, row counts and a content hash.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib


@dataclass
class Manifest:
    name: str
    version: str
    created_at: str
    feature_names: list[str]
    n_train: int
    n_val: int
    metrics: dict[str, Any]
    params: dict[str, Any]
    label_source: str
    git_sha: str = ""
    python: str = field(default_factory=platform.python_version)
    notes: str = ""
    content_sha256: str = ""


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""


class Registry:
    def __init__(self, root: str | Path = "artifacts"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, name: str, version: str) -> Path:
        d = self.root / name / version
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, name: str, obj: Any, manifest: Manifest, version: str | None = None) -> Path:
        version = version or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        manifest.version = version
        manifest.created_at = datetime.now(timezone.utc).isoformat()
        manifest.git_sha = _git_sha()

        d = self._dir(name, version)
        model_path = d / "model.joblib"
        joblib.dump(obj, model_path, compress=3)

        manifest.content_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
        (d / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2))

        # 'latest' pointer, written last so a crash mid-save never leaves a
        # dangling pointer to a half-written model
        latest = self.root / name / "LATEST"
        latest.write_text(version)
        print(f"[registry] saved {name}/{version}  sha={manifest.content_sha256[:12]}")
        return d

    def load(self, name: str, version: str = "latest") -> tuple[Any, Manifest]:
        if version == "latest":
            ptr = self.root / name / "LATEST"
            if not ptr.exists():
                raise FileNotFoundError(
                    f"no trained '{name}' model in {self.root}. Run train.py first."
                )
            version = ptr.read_text().strip()

        d = self.root / name / version
        obj = joblib.load(d / "model.joblib")
        man = Manifest(**json.loads((d / "manifest.json").read_text()))

        actual = hashlib.sha256((d / "model.joblib").read_bytes()).hexdigest()
        if man.content_sha256 and actual != man.content_sha256:
            raise RuntimeError(
                f"{name}/{version} failed integrity check — artifact modified since training"
            )
        return obj, man

    def list_versions(self, name: str) -> list[str]:
        p = self.root / name
        return sorted((d.name for d in p.iterdir() if d.is_dir()), reverse=True) \
            if p.exists() else []

    def exists(self, name: str) -> bool:
        return (self.root / name / "LATEST").exists()
