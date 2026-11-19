"""Eval gate: run the target repo's own tests before and after a mutation.

Semantics (fail closed):

* If no test command can be detected for ANY configured language, every
  mutation fails the gate — the loop never ships unverifiable changes.
* Baseline run (before mutation) must pass for the cycle to proceed at all;
  a repo whose tests are already broken is left alone.
* A mutation passes only if the after-run passes AND its return code equals
  the baseline's return code (no new failures, no newly-"fixed" flakes
  masking regressions).

The gate runs commands with a hard timeout and never interprets test output
beyond the exit code: the repo's own CI semantics decide, not this tool.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from adapters.base import LanguageAdapter
from loop.config.target import TargetConfig

DEFAULT_TIMEOUT = 300  # seconds, per test run


@dataclass
class GateRun:
    command: list[str]
    returncode: int | None
    timed_out: bool
    tail: str  # last ~15 lines, for provenance / debugging


class GateError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> GateRun:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
        return GateRun(cmd, proc.returncode, False, tail)
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
        err = ((e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
        tail = "\n".join((out + err).splitlines()[-15:])
        return GateRun(cmd, None, True, tail)
    except FileNotFoundError:
        return GateRun(cmd, None, False, f"command not found: {cmd[0]}")


def detect_command(cfg: TargetConfig, adapters: list[LanguageAdapter], worktree: Path) -> list[str] | None:
    """First adapter that detects a test command wins (languages are tried
    in the order the target config lists them)."""
    for lang in cfg.languages:
        adapter = adapters[lang] if isinstance(adapters, dict) else None
        if adapter is None:
            continue
        cmd = adapter.detect_test_command(worktree)
        if cmd:
            return cmd
    return None


def baseline(cfg: TargetConfig, adapters, worktree: Path) -> tuple[GateRun | None, str]:
    """Run the pre-mutation baseline. Returns (run, status).

    status is 'no-tests' (gate fails closed), 'failing' (repo already broken,
    cycle aborts) or 'passing'.
    """
    cmd = detect_command(cfg, adapters, worktree)
    if cmd is None:
        return None, "no-tests"
    run = _run(cmd, worktree)
    if run.returncode != 0:
        return run, "failing"
    return run, "passing"


def evaluate(
    cfg: TargetConfig,
    adapters,
    worktree: Path,
    baseline_run: GateRun | None,
) -> tuple[bool, GateRun | None, str]:
    """Post-mutation evaluation. Returns (passed, run, reason)."""
    cmd = detect_command(cfg, adapters, worktree)
    if cmd is None:
        return False, None, "no test command detected (fail closed)"
    run = _run(cmd, worktree)
    if run.timed_out:
        return False, run, "tests timed out after mutation"
    if run.returncode is None:
        return False, run, f"could not run tests: {run.tail[-120:]}"
    if run.returncode != 0:
        return False, run, f"tests fail after mutation (rc={run.returncode})"
    if baseline_run is not None and cfg.require_clean_gate and baseline_run.returncode != run.returncode:
        return False, run, "return code diverged from baseline"
    return True, run, "tests pass after mutation"
