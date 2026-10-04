"""neo4d - a self-learning, generalising core on 4D structures; every decision is an exhaustively judged law.

    PKG       this package
    KERNELS   the five authored laws, in C: router4d (k=3), router4d5 (k=5), harvest, pick, induce
    REPO      the repository root: results/, prompts/, docs/, and bench/ (fetched by scripts/fetch_bench.sh)
    BUILD     where compiled kernels go
"""
from pathlib import Path

__version__ = "0.1.0"
PKG = Path(__file__).resolve().parent
KERNELS = PKG / "kernels"
REPO = PKG.parent
BUILD = REPO / ".build"
BUILD.mkdir(exist_ok=True)
