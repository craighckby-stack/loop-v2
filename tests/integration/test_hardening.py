"""Integration tests for the v0.1.1 hardening batch:

- emit="branch" keeps the working copy AND writes a backup patch
- the Go adapter fails closed when the toolchain is absent
- unused-imports never touches __init__.py
- a detectable-but-missing runner yields 'unrunnable', not 'broken-baseline'
- zero strategies = legal health-check run
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "sample_repo"


def _make_target(tmp_path: Path, lp: Path, extra: str = "") -> Path:
    d = tmp_path / "targets" / "t"
    d.mkdir(parents=True, exist_ok=True)
    # overridable keys (emit/languages/strategies/include) live in 'extra';
    # defaults are supplied when the caller passes none
    defaults = (
        'emit = "patch"\nlanguages = ["python"]\n'
        'strategies = ["unused-imports", "strip-debug", "modernize-super"]\n'
        'include = ["**/*.py"]'
    )
    (d / "target.toml").write_text(
        f"""
[target]
id = "t"
provider = "local"
local_path = "{lp}"
base_branch = "main"
{defaults if not extra.strip() else extra.strip()}
exclude = ["**/tests/**", "**/test_*.py"]
max_prs_per_week = 3
max_runs_per_day = 5
""",
        encoding="utf-8",
    )
    return d


def _cycle(cfg_dir: Path, tmp_path: Path):
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle
    from loop.provenance import ProvenanceLog

    cfg = TargetConfig.load(cfg_dir / "target.toml")
    runs = tmp_path / "runs"
    log = ProvenanceLog(runs)
    return run_cycle(cfg, runs_dir=runs, log=log), runs


@pytest.fixture()
def fixture_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "upstream_repo"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_branch_emission_keeps_working_copy_and_backs_up(tmp_path, fixture_copy):
    tdir = _make_target(tmp_path, fixture_copy, extra='emit = "branch"')
    report, runs = _cycle(tdir, tmp_path)

    assert report.status == "ok", report.summary()
    assert report.emitted and report.emitted.startswith("branch:")
    # the working copy must still exist with the branch checked out
    wc = runs / report.run_id / "working-copy"
    assert wc.is_dir(), "branch emission must keep the working copy"
    # ...and the backup patch with the same content
    backup = runs / report.run_id / f"{report.run_id}.patch"
    assert backup.is_file()
    assert "super().__init__(name)" in backup.read_text()
    # the branch itself exists in the kept working copy
    import subprocess

    branches = subprocess.run(
        ["git", "-C", str(wc), "branch", "--list", "loop/*"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert report.run_id in branches


def test_go_target_fails_closed_without_toolchain(tmp_path):
    """A Go module target with no `go` binary installed must refuse to ship."""
    import shutil as _sh

    go_repo = tmp_path / "go-repo"
    (go_repo / "pkg").mkdir(parents=True)
    (go_repo / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n")
    (go_repo / "pkg" / "demo.go").write_text(
        "package pkg\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n"
    )
    (go_repo / "pkg" / "demo_test.go").write_text(
        "package pkg\n\nimport \"testing\"\n\n"
        "func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal(\"no\")\n\t}\n}\n"
    )
    (go_repo / ".loop-consent").write_text("consent = true\n")

    tdir = _make_target(
        tmp_path, go_repo,
        extra='languages = ["go"]\nstrategies = ["unused-imports"]\ninclude = ["**/*.go"]',
    )
    report, _runs = _cycle(tdir, tmp_path)

    # No go toolchain in this sandbox → command detected, runner missing.
    # Either way nothing ships; assert on both legitimate outcomes.
    assert report.status in ("unrunnable", "broken-baseline")
    assert report.emitted is None
    if report.status == "unrunnable":
        assert "cannot verify" in report.reason or "could not run" in report.reason


def test_unused_imports_never_touches_init_py(tmp_path, fixture_copy):
    pkg_init = fixture_copy / "demo_pkg" / "__init__.py"
    pkg_init.parent.mkdir(exist_ok=True)
    pkg_init.write_text("import json  # implicit re-export, must stay\n")
    tdir = _make_target(tmp_path, fixture_copy)
    report, _ = _cycle(tdir, tmp_path)

    assert report.status == "ok", report.summary()
    # the fixture's own strategies still applied
    assert "unused-imports" in report.strategies_kept
    # but never to the __init__.py
    assert "demo_pkg/__init__.py" not in report.files_changed
    assert "import json" in pkg_init.read_text()


def test_missing_runner_is_unrunnable_not_broken(tmp_path, fixture_copy):
    """No pytest module + no go binary: detection finds the unittest fallback,
    which exists; simulate the truly-missing-runner case via a bogus adapter."""
    from adapters.base import LanguageAdapter
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle
    from loop.provenance import ProvenanceLog

    class GhostRunner(LanguageAdapter):
        name = "ghost"

        def file_suffixes(self):
            return [".ghost"]

        def strategies(self):
            return {}

        def detect_test_command(self, worktree):
            return ["definitely-not-a-real-runner-xyz", "--all"]

    import adapters.languages.registry as reg

    tdir = _make_target(
        tmp_path, fixture_copy,
        extra='languages = ["ghost"]\nstrategies = []\ninclude = ["**/*.ghost"]',
    )
    cfg = TargetConfig.load(tdir / "target.toml")
    runs = tmp_path / "runs"
    log = ProvenanceLog(runs)

    original = dict(reg._ADAPTERS)
    reg._ADAPTERS["ghost"] = GhostRunner
    try:
        report = run_cycle(cfg, runs_dir=runs, log=log)
    finally:
        reg._ADAPTERS.clear()
        reg._ADAPTERS.update(original)

    assert report.status == "unrunnable"
    assert report.emitted is None


def test_zero_strategies_is_a_health_check(tmp_path, fixture_copy):
    tdir = _make_target(tmp_path, fixture_copy, extra="strategies = []")
    report, _ = _cycle(tdir, tmp_path)

    # consent ok, baseline green, nothing mutated → clean nothing-to-do
    assert report.status == "nothing-to-do"
    assert report.strategies_run == []
    assert report.emitted is None
