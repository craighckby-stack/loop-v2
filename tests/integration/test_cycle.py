"""Integration test: one full cycle against a local fixture repo.

This is the real proof: consent honoured, baseline green, strategies applied,
gate decides, patch emitted, provenance written.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "sample_repo"

TARGET_TOML = """
[target]
id = "fixture-demo"
provider = "local"
local_path = "{lp}"
base_branch = "main"
emit = "patch"
languages = ["python"]
strategies = ["unused-imports", "strip-debug", "modernize-super"]
include = ["**/*.py"]
exclude = ["**/tests/**", "**/test_*.py"]
max_prs_per_week = 3
max_runs_per_day = 2
"""


@pytest.fixture()
def fixture_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "upstream_repo"
    shutil.copytree(FIXTURE, dst)
    return dst


def _target(tmp_path: Path, lp: Path) -> Path:
    d = tmp_path / "targets" / "fixture-demo"
    d.mkdir(parents=True)
    (d / "target.toml").write_text(TARGET_TOML.format(lp=lp), encoding="utf-8")
    return d


def test_full_cycle_emits_patch(tmp_path, fixture_copy):
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle
    from loop.provenance import ProvenanceLog

    tdir = _target(tmp_path, fixture_copy)
    cfg = TargetConfig.load(tdir / "target.toml")
    runs = tmp_path / "runs"
    log = ProvenanceLog(runs)

    report = run_cycle(cfg, runs_dir=runs, log=log)

    assert report.status == "ok", report.summary()
    assert "modernize-super" in report.strategies_kept
    assert "strip-debug" in report.strategies_kept
    assert report.emitted and Path(report.emitted).is_file()
    patch = Path(report.emitted).read_text()
    assert "super().__init__(name)" in patch
    # the debug print must be REMOVED: it appears only as a '-' deletion line
    assert "\n+        print(f\"DEBUG" not in patch
    # fixture itself untouched
    assert (fixture_copy / "demo_pkg" / "core.py").read_text().count("DEBUG") == 1


def test_no_consent_refuses(tmp_path, fixture_copy):
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle
    from loop.provenance import ProvenanceLog

    (fixture_copy / ".loop-consent").unlink()
    tdir = _target(tmp_path, fixture_copy)
    cfg = TargetConfig.load(tdir / "target.toml")
    runs = tmp_path / "runs"
    log = ProvenanceLog(runs)

    report = run_cycle(cfg, runs_dir=runs, log=log)
    assert report.status == "refused"
    assert "opted in" in report.reason
    assert report.emitted is None


def test_broken_baseline_refuses_to_mutate(tmp_path, fixture_copy):
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle
    from loop.provenance import ProvenanceLog

    (fixture_copy / "tests" / "test_core.py").write_text(
        "import unittest\n\nclass T(unittest.TestCase):\n"
        "    def test_fails(self):\n        self.fail('pre-existing breakage')\n",
        encoding="utf-8",
    )
    tdir = _target(tmp_path, fixture_copy)
    cfg = TargetConfig.load(tdir / "target.toml")
    runs = tmp_path / "runs"
    log = ProvenanceLog(runs)

    report = run_cycle(cfg, runs_dir=runs, log=log)
    assert report.status == "broken-baseline"
    assert report.emitted is None


def test_daily_cap_blocks_second_run(tmp_path, fixture_copy):
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle
    from loop.provenance import ProvenanceLog

    tdir = _target(tmp_path, fixture_copy)
    cfg = TargetConfig.load(tdir / "target.toml")
    runs = tmp_path / "runs"
    log = ProvenanceLog(runs)
    # max_runs_per_day = 2, so third run must be refused
    for _ in range(2):
        r = run_cycle(cfg, runs_dir=runs, log=log)
        assert r.status in ("ok", "nothing-to-do")
    r3 = run_cycle(cfg, runs_dir=runs, log=log)
    assert r3.status == "refused"
    assert "daily" in r3.reason
