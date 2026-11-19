# Changelog

All notable changes to loop-v2. Dates are ISO-8601; versions follow semver.

## [0.1.1] - 2026-11-19

### Fixed
- **`emit = "branch"` no longer loses the changes.** Previously the working
  copy (and with it the branch) was deleted at cycle end; now branch
  emissions keep the working copy and additionally write a backup patch
  next to it (`<run-id>.patch`).
- **Gate status `unrunnable`** is now distinct from `broken-baseline`: a
  detected test command whose runner is missing or times out reports
  "cannot verify — nothing shipped" instead of wrongly claiming the repo's
  tests fail.
- **`unused-imports` never touches `__init__.py`**: implicit re-exports
  there are legitimate public API and invisible to static analysis; a
  false positive would break downstream imports.
- Version strings (provenance `tool` field, trailers, CLI) are derived from
  `loop.__version__` instead of hardcoded literals.
- **`acquire()` snapshot commits work on bare CI runners** (no global git
  identity): the local-provider snapshot commit now uses the same identity
  defaults as every other commit.

### Added
- **Go language adapter** (Phase 2 groundwork): `.go` file discovery and
  `go test ./...` detection for Go modules with test files. No mutation
  strategies yet — the adapter registers none, so Go targets fail closed
  until a Go strategy exists.
- **Commit identity defaults**: commits work in CI/containers without a
  global git config, attributed as `loop-v2 <loop-v2@users.noreply.github.com>`
  (a configured user identity always wins).
- **Zero-strategy targets are legal**: a "health-check" run that only
  verifies consent + baseline + provenance and proposes nothing.
- Unit tests for the GitHub REST path (`emit_pr` payload shape, fork head
  ref, error surfacing) with the network mocked; integration tests for
  branch emission, Go fail-closed, `__init__.py` safety, `unrunnable`
  status, and health-check runs. 57 tests total (was 46).
- GitHub Actions workflow: test suite + demo smoke test on Python
  3.11/3.12/3.13 with bare git config.

## [0.1.0] - 2026-11-19

Initial release.

- Engine: orchestrator cycle (acquire → etiquette pre-flight → baseline
  gate → mutate/gate/revert per strategy → emit → provenance).
- Etiquette enforced in code: consent marker, blocklist + `loop-stop`
  keyword, hard rate limits (runs/day, PRs/week), attributable trailers.
- Gate: the repo's own test command, before/after, fail closed.
- Python adapter + three AST strategies (`unused-imports`, `strip-debug`,
  `modernize-super`).
- CLI: `init-target`, `check`, `run`, `report`, `stop`.
- Append-only JSONL provenance log; local + GitHub providers.
- 46 tests, MIT license, docs (etiquette, adding strategies/adapters,
  provenance schema, self-hosting).
