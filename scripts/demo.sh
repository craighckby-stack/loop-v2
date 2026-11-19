#!/usr/bin/env bash
# End-to-end demo of loop-v2 against the bundled fixture repo.
# Run from the repo root:  bash scripts/demo.sh
# Everything happens in a scratch dir; the fixture is never mutated.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="$(mktemp -d)"
trap 'echo "demo dir: $DEMO (kept for inspection)"' EXIT

cp -r "$HERE/fixtures/sample_repo" "$DEMO/upstream-repo"

echo "== 1. init target bundle =="
PYTHONPATH="$HERE" python3 -m loop.cli init-target "$DEMO/targets/demo" \
    --local-path "$DEMO/upstream-repo"

echo; echo "== 2. check config =="
PYTHONPATH="$HERE" python3 -m loop.cli check "$DEMO/targets/demo"

echo; echo "== 3. run one cycle =="
PYTHONPATH="$HERE" python3 -m loop.cli run "$DEMO/targets/demo" \
    --runs-dir "$DEMO/runs"

echo; echo "== 4. report =="
PYTHONPATH="$HERE" python3 -m loop.cli report "$DEMO/targets/demo" \
    --runs-dir "$DEMO/runs"

echo; echo "== 5. upstream untouched =="
grep -q "DEBUG" "$DEMO/upstream-repo/demo_pkg/core.py" \
    && echo "ok: fixture still contains its original flaws"
