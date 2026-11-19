# Adding a strategy

A strategy decides **what** to change. It never decides whether the change
ships (that is the gate's job) and never touches git (that is the client's).

## The contract

```python
def mutate(worktree: Path, rel_files: list[str]) -> MutationResult:
    ...
```

- `worktree` — the checked-out working copy; mutate files in place.
- `rel_files` — repo-relative, POSIX-separator paths already filtered by
  the target's include/exclude and the language adapter's ownership.
- Returns a `MutationResult` (`loop/edits.py`) with one `Edit` per change.
  Return an empty result ("no edits proposed") when the repo is already
  clean — that is the common case and it is recorded as `skipped`.

The orchestrator calls you once per cycle. If your strategy raises, the
cycle catches it, reverts the working copy, records an `error` and moves
on — but do not rely on that; keep the strategy self-contained.

## Rules

1. **Deterministic.** Same input tree, same output edits. No randomness,
   no network, no clock reads. Reviewability depends on this.
2. **Structural over textual.** Parse, don't regex. Use the language's
   AST (Python: `ast`; see `strategies/common.py` for parse/apply helpers).
3. **Conservative.** Only propose a change when you can prove it is safe
   structurally. When in doubt, propose nothing. A strategy that ships
   nothing is fine; a strategy that breaks a repo is not.
4. **Line-based edits.** `Edit(start_line, end_line, new_text)` with
   1-based, end-exclusive ranges (Python `range` semantics). Multi-line
   calls/statements: skip rather than splice mid-expression.
5. **Rationale strings are user-facing.** They end up verbatim in the PR
   body: `"remove unused import(s): json, os"`, not `"cleanup"`.

## Walk-through: `strategies/strip_debug.py`

The full file is ~90 lines; the shape is:

```python
def propose_for_source(rel_path: str, source: str) -> list[Edit]:
    tree = parse_module(source)          # None on syntax error → skip
    if tree is None:
        return []
    edits = []
    for node in ast.walk(tree):
        ...match your pattern, check every safety condition...
        edits.append(Edit(file=rel_path,
                          start_line=node.lineno,
                          end_line=(node.end_lineno or node.lineno) + 1,
                          new_text="",
                          rationale="remove leftover debug statement"))
    return edits


def mutate(worktree: Path, rel_files: list[str]) -> MutationResult:
    edits = []
    for rel in rel_files:
        edits.extend(propose_for_source(rel, (worktree / rel).read_text(...)))
    for rel, file_edits in group_by_file(edits).items():
        apply_edits(worktree / rel, file_edits)   # common helper
    return MutationResult(strategy="strip-debug", edits=edits)
```

Note the safety conditions it checks before removing a `print`:
unambiguous debug prefix only, not inside `if __name__ == "__main__"`,
whole-statement removal. Each condition exists because a test failed
without it.

## Registering

Add the strategy id to the language adapter(s) that can run it:

```python
# adapters/languages/python_adapter/adapter.py
from strategies.my_strategy import mutate as my_strategy

def strategies(self):
    return {
        ...,
        "my-strategy": my_strategy,
    }
```

Then enable it per target in `target.toml`:

```toml
strategies = ["unused-imports", "my-strategy"]
```

## Testing

Add unit tests in `tests/unit/test_strategies.py` following the existing
pattern: a source string, the expected edits (and non-edits — the
negative cases matter more), then `_apply` and assert on the resulting
text. The integration suite picks new strategies up automatically when
listed in the fixture target.

The gate will catch behavioural breakage in integration; your unit tests
exist to pin the *conservatism*: every "keeps X" test is a promise that a
safe pattern is never touched.
