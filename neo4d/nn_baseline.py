"""Neural baselines for the sample-efficiency shootout - a 3-layer MLP and a small Transformer, CPU, PyTorch.

Standalone: reads tasks (JSON) and writes predictions (JSON); run with any Python that has torch.
    python nn_baseline.py tasks.json preds.json

Each task: a few (case -> action) examples over the 16 codes. Each model is trained from scratch on exactly those
examples until it fits them, then predicts all 16 codes. It always answers - neither architecture can refuse.
    MLP          4 input bits -> 64 -> 64 -> 16 classes
    Transformer  the 4 bits as 4 tokens, d = 32, 2 layers, 4 heads, mean-pooled -> 16 classes
"""
from __future__ import annotations

import json
import sys

import torch
import torch.nn as nn

torch.set_num_threads(1)
BITS = torch.tensor([[(c >> i) & 1 for i in range(4)] for c in range(16)], dtype=torch.float32)


class MLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(4, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, 4))

    def forward(self, x):
        return self.net(x)


class Tiny(nn.Module):
    def __init__(self, d=32):
        super().__init__()
        self.val = nn.Linear(1, d)
        self.pos = nn.Parameter(torch.randn(4, d) * 0.1)
        layer = nn.TransformerEncoderLayer(d, 4, 64, dropout=0.0, batch_first=True)
        self.enc = nn.TransformerEncoder(layer, 2)
        self.out = nn.Linear(d, 4)

    def forward(self, x):
        h = self.val(x.unsqueeze(-1)) + self.pos
        return self.out(self.enc(h).mean(1))


def fit_predict(make, cases, actions, seed, steps=400):
    torch.manual_seed(seed)
    m = make()
    opt = torch.optim.Adam(m.parameters(), lr=3e-3)
    x, y = BITS[cases], BITS[actions]
    for _ in range(steps):
        opt.zero_grad()
        loss = nn.functional.binary_cross_entropy_with_logits(m(x), y)
        loss.backward()
        opt.step()
    with torch.no_grad():
        bits = (m(BITS) > 0).long()
        return (bits * torch.tensor([1, 2, 4, 8])).sum(1).tolist()


def _one(args):
    i, t, models = args
    cases = [f for f, _ in t["examples"]]
    actions = [a for _, a in t["examples"]]
    out = {}
    if "mlp" in models:
        out["mlp"] = fit_predict(MLP, cases, actions, seed=i)
    if "transformer" in models:
        out["transformer"] = fit_predict(Tiny, cases, actions, seed=i)
    return out


def main(tasks_path, preds_path, models=("mlp", "transformer")):
    import multiprocessing as mp
    tasks = json.load(open(tasks_path))
    with mp.Pool(10) as pool:
        out = pool.map(_one, [(i, t, models) for i, t in enumerate(tasks)])
    json.dump(out, open(preds_path, "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], tuple(sys.argv[3].split(",")) if len(sys.argv) > 3 else ("mlp", "transformer"))
