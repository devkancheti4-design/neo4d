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


def build_kernel(name: str, flags: tuple = ()) -> Path:
    """Compile kernels/<name>.c once into .build/<name>.so - cached, and atomic (compile to a temporary file, then
    rename), so parallel workers never load a half-written library."""
    import os
    import subprocess
    import tempfile
    src, so = KERNELS / f"{name}.c", BUILD / f"{name}.so"
    if so.exists() and so.stat().st_mtime >= src.stat().st_mtime:
        return so
    fd, tmp = tempfile.mkstemp(suffix=".so", dir=BUILD)
    os.close(fd)
    subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-fwrapv", *flags, "-o", tmp, str(src)], check=True)
    os.replace(tmp, so)
    return so
