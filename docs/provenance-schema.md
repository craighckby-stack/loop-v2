# Provenance schema

Provenance is an append-only JSONL file, one JSON object per line, written
by `loop/provenance/log.py` to `<runs-dir>/provenance.jsonl`. Records are
never rewritten or deleted; `loop report` only reads.

Common fields on every record:

| field | type | meaning |
| --- | --- | --- |
| `record_id` | str | 12-hex random id, unique per record |
| `ts` | str | UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` |
| `tool` | str | `loop-v2/<version>` (on records that carry it) |

## Record kinds

### `run-start`

Written once when a cycle passes etiquette and actually begins.

```json
{"kind": "run-start", "run_id": "20261119-011250-752cbd3e",
 "target_id": "fixture-demo", "upstream": "0c699eb1daba...",
 "base_branch": "main", "strategies": ["unused-imports", "strip-debug"],
 "started_by": "cli", "tool": "loop-v2/0.1.0", "ts": "...", "record_id": "..."}
```

### `mutation`

One per attempted strategy, including skips and errors.

```json
{"kind": "mutation", "run_id": "...", "target_id": "...", "upstream": "...",
 "strategy": "modernize-super", "files": ["demo_pkg/core.py"],
 "gate": "test-gate", "verdict": "pass",
 "detail": "tests pass after mutation",
 "emitted": "runs/20261119-011250-752cbd3e/20261119-011250-752cbd3e.patch",
 "ts": "...", "record_id": "..."}
```

`verdict` ∈ `pass | fail | error | skipped`.

`emitted` is present only when this mutation's changes were included in the
emission (patch path, branch name, or PR URL). The rate limiter counts
`mutation` records with `emitted` against the weekly PR cap.

### `refusal`

Written when a cycle refuses before starting (no consent, blocklist, rate
limit). Contains `reason`. The corresponding working copy is discarded.

### `stop`

Written by `loop stop` when a maintainer's `loop-stop` reply is recorded.
Field `repo` = the repo to permanently refuse. `check_all` honours these
records on every future run.

### `run-end`

Written once when a cycle completes: `status`, `kept` (strategy list),
`emitted` (final artifact).

## Invariants

1. **Append-only.** No record is ever modified after write.
2. **Run ids are unique** (`YYYYMMDD-HHMMSS-<8hex>`), so a run directory
   and its patch file are traceable to their records and vice versa.
3. **`upstream` ties every mutation to the exact commit it was built
   against** — a mutation that only worked on a stale base is identifiable
   months later.
4. **The rate limiter derives entirely from this file** — caps are enforced
   from history that the tool itself cannot silently edit (it has no
   rewrite API at all).

## Querying

`loop report` prints a human-readable timeline. For anything else, the file
is plain JSONL — `jq`, pandas, grep all work directly:

```bash
jq -c 'select(.kind=="mutation" and .verdict=="pass")' provenance.jsonl
```
