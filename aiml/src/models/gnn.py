"""
GraphSAGE over the transaction graph — optional.

Why a GNN on top of the gradient-boosted models: the tabular features
summarise a wallet's own neighbourhood, but they cannot express "this
wallet's counterparties themselves behave like mule accounts". Message
passing learns exactly that second-order structure, which is where
laundering networks actually live.

Degrades cleanly: if torch / torch-geometric are absent, HAS_TORCH is
False and the training pipeline skips this stage with a note rather than
crashing. That keeps `pip install -r requirements.txt` light for anyone
who just wants the four tabular models.

Install:
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install torch-geometric
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn.functional as F
    from torch_geometric.data import Data
    from torch_geometric.nn import SAGEConv
    HAS_TORCH = True
except ImportError:                                    # pragma: no cover
    HAS_TORCH = False
    torch = None


if HAS_TORCH:

    class GraphSAGERisk(torch.nn.Module):
        """3-layer GraphSAGE with residual connections and dropout."""

        def __init__(self, in_dim: int, hidden: int = 128,
                     layers: int = 3, dropout: float = 0.3):
            super().__init__()
            self.dropout = dropout
            self.convs = torch.nn.ModuleList()
            self.norms = torch.nn.ModuleList()
            d = in_dim
            for _ in range(layers):
                self.convs.append(SAGEConv(d, hidden))
                self.norms.append(torch.nn.LayerNorm(hidden))
                d = hidden
            self.head = torch.nn.Linear(hidden, 1)

        def forward(self, x, edge_index):
            h = x
            for conv, norm in zip(self.convs, self.norms):
                h_new = F.relu(norm(conv(h, edge_index)))
                h_new = F.dropout(h_new, p=self.dropout, training=self.training)
                # residual once dimensions match
                h = h_new + h if h.shape == h_new.shape else h_new
            return self.head(h).squeeze(-1)

        @torch.no_grad()
        def embed(self, x, edge_index):
            h = x
            for conv, norm in zip(self.convs, self.norms):
                h = F.relu(norm(conv(h, edge_index)))
            return h


class GNNWrapper:
    """Keeps the same fit / predict surface as the tabular models."""

    def __init__(self, hidden: int = 128, layers: int = 3,
                 dropout: float = 0.3, epochs: int = 60, lr: float = 5e-3):
        if not HAS_TORCH:
            raise ImportError(
                "torch / torch-geometric not installed — GNN stage unavailable"
            )
        self.cfg = dict(hidden=hidden, layers=layers, dropout=dropout,
                        epochs=epochs, lr=lr)
        self.model = None
        self.feature_names: list[str] = []
        self.node_index: dict[str, int] = {}
        self.metrics: dict = {}

    @staticmethod
    def build_graph(features: pd.DataFrame, edges: list[tuple[str, str]],
                    address_col: str = "address"):
        """Feature frame + edge list -> a PyG Data object."""
        addrs = features[address_col].tolist()
        idx = {a: i for i, a in enumerate(addrs)}
        feat_cols = [c for c in features.columns if c != address_col]

        x = torch.tensor(features[feat_cols].values, dtype=torch.float)
        # normalise per column; raw USD values would swamp the ratios
        x = (x - x.mean(0)) / (x.std(0) + 1e-8)

        pairs = [(idx[a], idx[b]) for a, b in edges if a in idx and b in idx]
        if not pairs:
            raise ValueError("no edges map onto the feature frame")
        ei = torch.tensor(pairs, dtype=torch.long).t().contiguous()
        # undirected: message passing should flow both ways
        ei = torch.cat([ei, ei.flip(0)], dim=1)

        return Data(x=x, edge_index=ei), idx, feat_cols

    def fit(self, data, y: np.ndarray, train_mask: np.ndarray,
            val_mask: np.ndarray | None = None):
        y_t = torch.tensor(y, dtype=torch.float)
        tr = torch.tensor(train_mask, dtype=torch.bool)
        va = torch.tensor(val_mask, dtype=torch.bool) if val_mask is not None else None

        self.model = GraphSAGERisk(
            data.num_node_features, self.cfg["hidden"],
            self.cfg["layers"], self.cfg["dropout"])
        opt = torch.optim.AdamW(self.model.parameters(), lr=self.cfg["lr"],
                                weight_decay=1e-4)

        pos = float(y[train_mask].sum())
        neg = float(train_mask.sum() - pos)
        pos_weight = torch.tensor([neg / max(pos, 1.0)])

        best_val, best_state, patience = -1.0, None, 0
        for epoch in range(self.cfg["epochs"]):
            self.model.train()
            opt.zero_grad()
            out = self.model(data.x, data.edge_index)
            loss = F.binary_cross_entropy_with_logits(
                out[tr], y_t[tr], pos_weight=pos_weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            opt.step()

            if va is not None and va.sum() > 0 and epoch % 5 == 0:
                self.model.eval()
                with torch.no_grad():
                    p = torch.sigmoid(self.model(data.x, data.edge_index))[va].numpy()
                yv = y[val_mask]
                if len(np.unique(yv)) > 1:
                    from sklearn.metrics import average_precision_score
                    ap = average_precision_score(yv, p)
                    if ap > best_val:
                        best_val, patience = ap, 0
                        best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
                    else:
                        patience += 1
                        if patience >= 6:
                            break

        if best_state is not None:
            self.model.load_state_dict(best_state)
        self.metrics = {"val_auc_pr": float(best_val) if best_val >= 0 else None,
                        "epochs_run": epoch + 1}
        return self

    @torch.no_grad()
    def predict_proba(self, data) -> np.ndarray:
        self.model.eval()
        return torch.sigmoid(self.model(data.x, data.edge_index)).numpy()

    @torch.no_grad()
    def embeddings(self, data) -> np.ndarray:
        self.model.eval()
        return self.model.embed(data.x, data.edge_index).numpy()
