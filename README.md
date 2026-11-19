# loop-v2

An opt-in, target-agnostic autonomous code-improvement loop.

The engine pulls a target repository into a working copy, applies mutation
strategies, evaluates every mutation with **the repo's own test command**,
and emits only passing mutations as reviewable patches / branches / PRs.
It refuses to run against any repo that has not explicitly consented.

```
acquire working copy
   → etiquette pre-flight (consent, blocklist, rate limits)
   → baseline gate (the repo's own tests must pass BEFORE any mutation)
   → for each strategy: apply → gate → keep or revert
   → emit surviving changes (patch / branch / PR)
   → provenance for every step
```

## Design principles

1. **Opt-in only.** No `.loop-consent` marker on the base branch, no run.
2. **The repo's own tests are the eval.** The tool imposes no success
   criteria of its own; it runs what the repo already runs and fails closed
   (no tests detected → nothing ships).
3. **Everything is attributable.** Every commit carries `X-Loop-Tool` and
   `X-Loop-Stop` trailers; every run appends to a write-once provenance log.
4. **Hard rate limits.** Per-target caps on runs/day and PRs/week, tightened
   further by whatever the consent file allows.
5. **Any code, via adapters.** The engine is language-agnostic; a language
   is a plugin that provides file discovery, edits and test detection.
   Python ships built-in; see `docs/adding-a-language-adapter.md`.

## Install

```bash
pip install .          # installs the `loop` command
```

Or run from a checkout without installing:

```bash
python -m loop.cli --help
```

Requires Python 3.11+ and git. No third-party dependencies.

## Quick start

```bash
# 1. create a target bundle for a local checkout
loop init-target targets/my-repo --local-path /path/to/repo

# 2. validate config, see which test command the gate would run
loop check targets/my-repo

# 3. run one cycle
loop run targets/my-repo

# 4. read what happened
loop report targets/my-repo
```

The target repo must contain a `.loop-consent` marker on its base branch:

```toml
consent = true
contact = "maintainer@example.com"
max_prs_per_week = 3
```

(A template is generated in the target bundle as `CONSENT-MARKER-TEMPLATE`
— hand it to the upstream maintainers; they decide.)

For GitHub targets, set `provider = "github"` and `repo = "owner/name"` in
`target.toml`, and export `LOOP_GH_TOKEN` with repo/fork scope to enable
`emit = "pr"`.

## What's in the box

| Piece | Where | What it does |
| --- | --- | --- |
| Orchestrator | `loop/orchestrator.py` | one cycle: acquire → guard → mutate → gate → emit |
| Etiquette guards | `loop/etiquette/` | consent marker, blocklist, rate limits, stop keyword |
| Git client | `loop/gitclient/` | clone/branch/commit/patch; fork push + PR via GitHub REST |
| Provenance | `loop/provenance/` | append-only JSONL run log |
| Language adapters | `adapters/` | plugin model; `python` built in |
| Strategies | `strategies/` | `unused-imports`, `strip-debug`, `modernize-super` |
| Gate | `gates/` | runs the repo's own test command before/after |
| CLI | `loop/cli.py` | `init-target`, `check`, `run`, `report`, `stop` |

## Stopping the tool

Upstream maintainers have three ways, all honoured:

- reply `loop-stop` to any emitted PR (record it via `loop stop`);
- delete the `.loop-consent` marker (or set `consent = false`);
- appear on the blocklist (maintained in the tool's repo).

## Development

```bash
python -m pytest tests/       # 46 tests: unit + integration
```

The integration tests run full cycles against `fixtures/sample_repo` —
consent honoured, baseline gated, patches emitted, fixture never mutated.

## Status

Phase 1 of the roadmap in `docs/`: engine + local/GitHub providers + Python
adapter + three deterministic strategies + repo-CI gate + CLI. Phase 2
(more language adapters) and phase 3 (GitHub App hosting) are next; see
`docs/self-hosting.md` for the current deployment model.

MIT licensed. See `LICENSE`.
