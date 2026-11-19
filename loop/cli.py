"""loop-v2 command line interface.

    loop init-target <dir> [--repo owner/name] [--local-path PATH]
    loop check <target-dir>          etiquette + config + gate dry-run
    loop run <target-dir>            one full cycle
    loop report [<target-dir>]       read the provenance log
    loop stop <owner/name>           record a permanent stop (blocklist entry)

Global options:
    --runs-dir PATH   where working copies / patches / provenance live
                      (default: ./.loop-runs next to the target dir)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loop import TOOL_NAME, TOOL_VERSION
from loop.etiquette import Blocklist, ConsentError
from loop.provenance import ProvenanceLog

TARGET_TOML_TEMPLATE = """\
# loop-v2 target configuration.
# Docs: docs/etiquette.md (consent), docs/adding-a-strategy.md (strategies).
[target]
id = "{id}"
provider = "{provider}"            # 'local' or 'github'
repo = "{repo}"                    # 'owner/name' (github provider)
local_path = "{local_path}"        # path to the repo checkout (local provider)
base_branch = "main"
emit = "patch"                     # 'patch' | 'branch' | 'pr'

languages = ["python"]
strategies = ["unused-imports", "strip-debug", "modernize-super"]

include = ["**/*.py"]
exclude = ["**/tests/**", "**/test_*.py", "**/.venv/**", "**/docs/**"]

# Etiquette: hard caps, on top of the consent file's own limits.
max_prs_per_week = 3
max_runs_per_day = 2
require_clean_gate = true
"""

CONSENT_TEMPLATE = """\
# Commit this file to your default branch to let loop-v2 propose changes.
# Remove it (or set consent = false) to revoke at any time.
consent = true
contact = "maintainer@example.com"
max_prs_per_week = 3
"""


def _runs_dir_for(target_dir: Path, args_runs_dir: str | None) -> Path:
    if args_runs_dir:
        return Path(args_runs_dir)
    return target_dir.parent / ".loop-runs"


def cmd_init_target(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    cfg_file = d / "target.toml"
    if cfg_file.exists():
        print(f"refusing to overwrite {cfg_file}", file=sys.stderr)
        return 1
    cfg_file.write_text(
        TARGET_TOML_TEMPLATE.format(
            id=d.name,
            provider="local" if not args.repo else "github",
            repo=args.repo or "",
            local_path=str(Path(args.local_path or ".").resolve()),
        ),
        encoding="utf-8",
    )
    notes = d / "NOTES.md"
    if not notes.exists():
        notes.write_text(
            f"# {d.name}\n\nWho owns the upstream repo, PR etiquette, gotchas.\n",
            encoding="utf-8",
        )
    consent = d / "CONSENT-MARKER-TEMPLATE"
    if not consent.exists():
        consent.write_text(CONSENT_TEMPLATE, encoding="utf-8")
    print(f"created {cfg_file}")
    print(f"created {notes}")
    print(f"created {consent}  (give this to the upstream maintainers)")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from loop.config import TargetConfig

    target_dir = Path(args.target_dir)
    try:
        cfg = TargetConfig.load(target_dir / "target.toml")
    except Exception as e:  # noqa: BLE001
        print(f"config error: {e}", file=sys.stderr)
        return 2

    print(f"target     : {cfg.target_id}")
    print(f"provider   : {cfg.provider} ({cfg.repo or cfg.local_path})")
    print(f"languages  : {', '.join(cfg.languages)}")
    print(f"strategies : {', '.join(cfg.strategies)}")
    print(f"emit       : {cfg.emit}")

    # gate dry-run on the source of the working copy we would acquire
    from adapters import get_adapter
    from gates.test_gate import detect_command

    src = Path(cfg.local_path) if cfg.provider == "local" else None
    adapters = {}
    for lang in cfg.languages:
        try:
            adapters[lang] = get_adapter(lang)
        except KeyError as e:
            print(f"adapter missing: {e}", file=sys.stderr)
            return 2
    if src is not None and src.is_dir():
        cmd = detect_command(cfg, adapters, src)
        print(f"test cmd   : {' '.join(cmd) if cmd else 'NOT DETECTED (gate will fail closed)'}")
        if not Blocklist.load().blocked(cfg.repo or cfg.target_id):
            print("blocklist  : clear")
    print("OK: config valid; consent is checked at run time against the base branch")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from loop.config import TargetConfig
    from loop.orchestrator import run_cycle

    target_dir = Path(args.target_dir)
    try:
        cfg = TargetConfig.load(target_dir / "target.toml")
    except Exception as e:  # noqa: BLE001
        print(f"config error: {e}", file=sys.stderr)
        return 2

    runs_dir = _runs_dir_for(target_dir, args.runs_dir)
    log = ProvenanceLog(runs_dir)
    try:
        report = run_cycle(
            cfg,
            runs_dir=runs_dir,
            log=log,
            started_by=args.started_by,
            keep_working_copy=args.keep_working_copy,
        )
    except ConsentError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    print(report.summary())
    if report.status == "ok":
        return 0
    if report.status in ("refused",):
        return 3
    return 1


def cmd_report(args: argparse.Namespace) -> int:
    if args.target_dir:
        runs_dir = _runs_dir_for(Path(args.target_dir), args.runs_dir)
    else:
        runs_dir = Path(args.runs_dir or ".loop-runs")
    log = ProvenanceLog(runs_dir)
    records = log.records()
    if not records:
        print(f"no provenance records in {log.path}")
        return 0
    print(f"{len(records)} records in {log.path}\n")
    for r in records:
        kind = r.get("kind", "?")
        if kind == "run-start":
            print(f"[{r['ts']}] RUN    {r['run_id']} target={r['target_id']} sha={r['upstream'][:10]}")
        elif kind == "mutation":
            verdict = r["verdict"].upper()
            strat = r["strategy"]
            emitted = f" -> {r['emitted']}" if r.get("emitted") else ""
            print(f"[{r['ts']}] {verdict:<7} {strat:<20} {r.get('detail', '')[:80]}{emitted}")
        elif kind == "refusal":
            print(f"[{r['ts']}] REFUSED {r.get('reason', '')[:100]}")
        elif kind == "run-end":
            print(f"[{r['ts']}] END    {r['run_id']} kept={r.get('kept')} emitted={r.get('emitted')}")
        elif kind == "stop":
            print(f"[{r['ts']}] STOP   {r.get('repo', '')}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    target_dir = Path(args.target_dir)
    runs_dir = _runs_dir_for(target_dir, args.runs_dir)
    log = ProvenanceLog(runs_dir)
    log.append({"kind": "stop", "repo": args.repo, "by": args.started_by})
    print(f"recorded permanent stop for {args.repo}; future runs will refuse.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="loop", description=f"{TOOL_NAME} {TOOL_VERSION}: opt-in autonomous code-improvement loop")
    p.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init-target", help="create a new target bundle")
    sp.add_argument("dir")
    sp.add_argument("--repo", help="owner/name for the github provider")
    sp.add_argument("--local-path", help="path to a local checkout for the local provider")
    sp.set_defaults(func=cmd_init_target)

    sp = sub.add_parser("check", help="validate config + etiquette dry-run")
    sp.add_argument("target_dir")
    sp.add_argument("--runs-dir")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("run", help="run one full cycle")
    sp.add_argument("target_dir")
    sp.add_argument("--runs-dir")
    sp.add_argument("--started-by", default="cli")
    sp.add_argument("--keep-working-copy", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("report", help="read the provenance log")
    sp.add_argument("target_dir", nargs="?")
    sp.add_argument("--runs-dir")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("stop", help="record a permanent stop for a repo")
    sp.add_argument("target_dir")
    sp.add_argument("repo")
    sp.add_argument("--runs-dir")
    sp.add_argument("--started-by", default="cli")
    sp.set_defaults(func=cmd_stop)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
