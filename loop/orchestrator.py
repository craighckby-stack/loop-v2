"""Orchestrator: one loop cycle.

    acquire working copy
        → etiquette pre-flight (consent, blocklist, rate limits)
        → baseline gate (repo's own tests must pass BEFORE any mutation)
        → for each strategy: apply → gate → keep or revert
        → emit surviving changes (patch / branch / PR)
        → provenance for every step

The orchestrator owns none of the policy: consent lives in etiquette,
evaluation lives in gates, mutation lives in strategies, git lives in the
client. It only sequences them and records what happened.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from adapters import get_adapter
from gates.test_gate import GateRun, baseline, evaluate
from loop import TOOL_NAME, TOOL_VERSION
from loop.config.target import TargetConfig
from loop.etiquette import Blocklist, ConsentError, RateLimiter, check_all
from loop.gitclient import GitClient
from loop.provenance import ProvenanceLog, new_run_id


@dataclass
class CycleReport:
    run_id: str
    target_id: str
    upstream: str
    status: str = "ok"               # ok | refused | no-tests | broken-baseline | nothing-to-do
    reason: str = ""
    strategies_run: list[str] = field(default_factory=list)
    strategies_kept: list[str] = field(default_factory=list)
    emitted: str | None = None       # patch path / branch name / PR url
    files_changed: list[str] = field(default_factory=list)
    gate_tail: str = ""

    def summary(self) -> str:
        lines = [
            f"run {self.run_id} on {self.target_id} @ {self.upstream[:12]}",
            f"  status : {self.status}" + (f" ({self.reason})" if self.reason else ""),
            f"  tried  : {', '.join(self.strategies_run) or '-'}",
            f"  kept   : {', '.join(self.strategies_kept) or '-'}",
            f"  emitted: {self.emitted or '-'}",
        ]
        if self.files_changed:
            lines.append(f"  files  : {', '.join(self.files_changed)}")
        return "\n".join(lines)


def run_cycle(
    cfg: TargetConfig,
    runs_dir: Path,
    log: ProvenanceLog,
    started_by: str = "cli",
    keep_working_copy: bool = False,
    blocklist: Blocklist | None = None,
) -> CycleReport:
    runs_dir = Path(runs_dir)
    run_id = new_run_id()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    wc = run_dir / "working-copy"

    git = GitClient(cfg)
    report = CycleReport(run_id=run_id, target_id=cfg.target_id, upstream="")

    # ---- 1. acquire ------------------------------------------------------
    try:
        git.acquire(wc)
    except Exception as e:  # noqa: BLE001 - surfaced to the user as status
        report.status, report.reason = "refused", f"acquire failed: {e}"
        return report
    report.upstream = git.head_sha(wc)

    # ---- 2. etiquette pre-flight ----------------------------------------
    try:
        consent = check_all(cfg, wc, log, blocklist)
    except ConsentError as e:
        report.status, report.reason = "refused", str(e)
        log.append({"kind": "refusal", "run_id": run_id, "target_id": cfg.target_id,
                    "reason": str(e), "tool": f"{TOOL_NAME}/{TOOL_VERSION}"})
        _cleanup(wc, run_dir, keep_working_copy)
        return report

    limiter = RateLimiter(log)
    allowed, why = limiter.check(cfg, consent)
    if not allowed:
        report.status, report.reason = "refused", why
        log.append({"kind": "refusal", "run_id": run_id, "target_id": cfg.target_id,
                    "reason": why, "tool": f"{TOOL_NAME}/{TOOL_VERSION}"})
        _cleanup(wc, run_dir, keep_working_copy)
        return report

    log.run_record(
        run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
        base_branch=cfg.base_branch, strategies=cfg.strategies, started_by=started_by,
    )

    # ---- 3. adapters + file scope ----------------------------------------
    adapters = {}
    for lang in cfg.languages:
        try:
            adapters[lang] = get_adapter(lang)
        except KeyError:
            report.status, report.reason = "refused", f"no adapter for language {lang!r}"
            _cleanup(wc, run_dir, keep_working_copy)
            return report

    def scoped_files() -> list[str]:
        out = []
        for p in sorted(wc.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(wc).as_posix()
            if rel.startswith(".git/"):
                continue
            if "__pycache__" in p.parts or rel.endswith((".pyc", ".pyo", ".so", ".lock")):
                continue
            if cfg.matches(rel) and any(a.owns(rel) for a in adapters.values()):
                out.append(rel)
        return out

    # ---- 4. baseline gate -------------------------------------------------
    base_run, base_status = baseline(cfg, adapters, wc)
    if base_status == "no-tests":
        report.status = "no-tests"
        report.reason = "no test command detected; gate fails closed, nothing shipped"
        log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                            strategy="(baseline)", files=[], gate="test-gate",
                            verdict="fail", detail=report.reason)
        _cleanup(wc, run_dir, keep_working_copy)
        return report
    if base_status == "failing":
        report.status = "broken-baseline"
        report.reason = "target's tests already fail before any mutation; refusing to touch it"
        log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                            strategy="(baseline)", files=[], gate="test-gate",
                            verdict="fail", detail="baseline failing: " + (base_run.tail[-200:] if base_run else ""))
        _cleanup(wc, run_dir, keep_working_copy)
        return report

    # ---- 5. mutate → gate → keep/revert, one strategy at a time ----------
    kept: list[str] = []
    files_changed: list[str] = []
    for strategy_id in cfg.strategies:
        available = {}
        for a in adapters.values():
            available.update(a.strategies())
        fn = available.get(strategy_id)
        if fn is None:
            log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                                strategy=strategy_id, files=[], gate="-",
                                verdict="skipped", detail="strategy not available for configured languages")
            continue

        sha_before = git.head_sha(wc)
        try:
            result = fn(wc, scoped_files())
        except Exception as e:  # noqa: BLE001 - strategy bugs must not kill the cycle
            git.checkout_reset(wc, sha_before)
            log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                                strategy=strategy_id, files=[], gate="-",
                                verdict="error", detail=f"strategy raised: {e}")
            continue

        report.strategies_run.append(strategy_id)
        if result.empty:
            log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                                strategy=strategy_id, files=[], gate="-",
                                verdict="skipped", detail="no edits proposed")
            continue

        passed, run, why = evaluate(cfg, adapters, wc, base_run)
        if passed:
            msg = f"loop-v2: {strategy_id}\n\nApplied by an opt-in autonomous loop; the repo's own tests pass before and after."
            git.commit_all(wc, msg)
            kept.append(strategy_id)
            files_changed.extend(git.changed_files(wc, sha_before))
            log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                                strategy=strategy_id, files=git.changed_files(wc, sha_before),
                                gate="test-gate", verdict="pass", detail=why)
        else:
            git.checkout_reset(wc, sha_before)
            log.mutation_record(run_id=run_id, target_id=cfg.target_id, upstream=report.upstream,
                                strategy=strategy_id, files=[e.file for e in result.edits],
                                gate="test-gate", verdict="fail",
                                detail=why + " | tail: " + (run.tail[-200:] if run else ""))

    report.strategies_kept = kept
    report.files_changed = sorted(set(files_changed))

    if not kept:
        report.status = "nothing-to-do"
        report.reason = "no strategy produced a passing mutation"
        _cleanup(wc, run_dir, keep_working_copy)
        return report

    # ---- 6. emit -----------------------------------------------------------
    branch = f"{cfg.branch_prefix}{run_id}"
    base_sha = report.upstream
    try:
        if cfg.emit == "patch":
            out = run_dir / f"{run_id}.patch"
            report.emitted = git.emit_patch(wc, base_sha, out)
        elif cfg.emit == "branch":
            git.create_branch(wc, branch)
            report.emitted = git.emit_branch(wc, branch)
        elif cfg.emit == "pr":
            title = f"loop-v2: {', '.join(kept)}"
            body = _pr_body(run_id, cfg, kept, report.files_changed)
            report.emitted = git.emit_pr(wc, branch, title, body)
    except Exception as e:  # noqa: BLE001
        report.status, report.reason = "ok", f"emission degraded: {e}"
        out = run_dir / f"{run_id}.patch"
        try:
            report.emitted = git.emit_patch(wc, base_sha, out)
        except Exception:
            report.emitted = None

    report.status = "ok"
    log.append({"kind": "run-end", "run_id": run_id, "target_id": cfg.target_id,
                "status": report.status, "kept": kept, "emitted": report.emitted})
    if not keep_working_copy:
        _cleanup(wc, run_dir, keep_working_copy)
    return report


def _pr_body(run_id: str, cfg: TargetConfig, kept: list[str], files: list[str]) -> str:
    from loop.etiquette import commit_trailers

    return (
        f"Autonomous changes produced by **{TOOL_NAME}** `{TOOL_VERSION}` "
        f"(opt-in; consent marker present on `{cfg.base_branch}`).\n\n"
        f"- run: `{run_id}`\n"
        f"- strategies kept: {', '.join(kept)}\n"
        f"- files: {len(files)}\n"
        f"- gate: the repo's own test command was run before and after; both green.\n\n"
        f"Maintainers: to stop this tool from ever touching this repo, reply `{_stop()}` "
        f"or delete the `.loop-consent` marker.\n\n"
        f"{'  '.join(commit_trailers())}"
    )


def _stop() -> str:
    from loop import STOP_KEYWORD

    return STOP_KEYWORD


def _cleanup(wc: Path, run_dir: Path, keep: bool) -> None:
    if keep:
        return
    if wc.exists():
        shutil.rmtree(wc, ignore_errors=True)
    # keep run_dir: it holds the patch + provenance breadcrumbs
