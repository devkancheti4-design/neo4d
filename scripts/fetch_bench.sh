#!/usr/bin/env bash
# Fetch every benchmark neo4d measures against into bench/ (not committed). ~1 GB, a few minutes.
#   BugsInPy (Python), Defects4J patches (Java), Defects4C (C/C++), fluid-router's 33-bug corpus, QuixBugs,
#   fluidnet (its click race data), and click at the race's commit with its own test environment.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p bench && cd bench
[ -d BugsInPy ]     || git clone -q --depth 1 https://github.com/soarsmu/BugsInPy.git
[ -d defects4j ]    || { git clone -q --depth 1 --filter=blob:none --sparse https://github.com/rjust/defects4j.git && (cd defects4j && git sparse-checkout set framework/projects); }
[ -d defects4c ]    || git clone -q --depth 1 https://github.com/defects4c/defects4c.git
[ -d fluid-router ] || git clone -q --depth 1 https://github.com/devkancheti4-design/fluid-router.git
[ -d QuixBugs ]     || git clone -q --depth 1 https://github.com/jkoppel/QuixBugs.git
[ -d fluidnet ]     || git clone -q --depth 1 https://github.com/devkancheti4-design/fluidnet.git
[ -d click ]        || { git clone -q https://github.com/pallets/click.git && git -C click checkout -q 06b2a67; }
PY=${PYTHON:-python3}
[ -d tvenv ] || { "$PY" -m venv tvenv && tvenv/bin/pip install -q pytest pytest-cov pytest-timeout ./click; }
# per-test coverage of click, for PICK's EXECUTED / MANY_TESTS bits (C tracer: sys.monitoring drops contexts)
if [ ! -f pick_click/cov.json ]; then
  rm -rf pick_click && mkdir pick_click && git -C click archive HEAD | tar -x -C pick_click
  (cd pick_click && COVERAGE_CORE=ctrace PYTHONPATH=src ../tvenv/bin/python -m pytest -q -p no:cacheprovider -W default \
      --tb=no --cov=click --cov-context=test --cov-report= >/dev/null && \
   COVERAGE_CORE=ctrace ../tvenv/bin/python -m coverage json --show-contexts -o cov.json >/dev/null)
fi
echo "bench/ ready"
