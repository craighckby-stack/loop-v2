# Adding a language adapter

"Any code" is a plugin model, not a universal mutator. A language adapter
teaches the engine about one language: which files it owns, which strategies
can run on it, and how to detect that language's test command. Everything
else (etiquette, gate sequencing, git, provenance) is language-agnostic.

## The interface

Subclass `adapters.base.LanguageAdapter`:

```python
class MyLangAdapter(LanguageAdapter):
    name = "mylang"                    # what target.toml lists under languages

    def file_suffixes(self) -> list[str]:
        return [".ml"]                 # files this adapter claims

    def strategies(self) -> dict[str, object]:
        return {"unused-imports": mylang_unused_imports}   # may be partial

    def detect_test_command(self, worktree: Path) -> list[str] | None:
        ...
```

`owns()` comes free: a file belongs to you if it ends in one of your
suffixes. Return a partial strategy dict if the language cannot support
some strategies — the orchestrator records those as `skipped` per target.

## detect_test_command: the important one

The gate's whole value is running the repo's own tests. For your language,
find the command that does that in `worktree`, or return `None`:

```python
def detect_test_command(self, worktree):
    wt = Path(worktree)
    if (wt / "go.mod").is_file():
        return ["go", "test", "./..."]
    return None
```

Detection rules:

- **fail closed.** `None` means "no tests found" → the gate refuses every
  mutation for this language. Prefer false negatives over guessing wrong.
- **no installs.** Use runners that are either vendored (gradients like
  `go test`) or already configured in the repo (`python -m pytest`). Never
  `pip install` / `npm install` anything at gate time.
- **check markers, then verify the shape.** Config file present AND test
  files present (see the Python adapter's `pytest.ini` + `tests/` logic).
- **hermetic.** The command runs inside the working copy with a timeout;
  assume no network and no shared caches.

## Registering

One line in `adapters/languages/registry.py`:

```python
from adapters.languages.mylang.adapter import MyLangAdapter

_ADAPTERS = {
    PythonAdapter.name: PythonAdapter,
    GoAdapter.name: GoAdapter,
    MyLangAdapter.name: MyLangAdapter,
}
```

Shipping an adapter with **no strategies is legitimate** — that is exactly
what the Go adapter does today: it contributes file discovery and gate
detection, registers an empty strategy dict, and Go targets fail closed
until a Go strategy exists. Discovery + gate first, mutations second, is
the recommended order for every new language.

## Strategies for a new language

You have two options:

1. **Port a strategy** (recommended first step): same idea, your language's
   parser. Follow `docs/adding-a-strategy.md`; the AST changes, the
   conservatism must not.
2. **Reuse via a universal layer** (later): tree-sitter or LSP based edits
   can back the same strategy ids for many languages at once. The
   `Edit`/`MutationResult` model in `loop/edits.py` is deliberately
   language-neutral so this can be slotted in behind `strategies()`.

## Testing

- unit: `owns()` suffix logic; `detect_test_command()` against synthetic
  trees (with and without markers — both branches);
- integration: a small fixture repo in your language (see
  `fixtures/sample_repo` for the Python one) plus one target config;
  the existing cycle tests then apply unchanged.

## Checklist for merging a new adapter

- [ ] returns `None` from detect_test_command when nothing certain is found
- [ ] strategy dict only lists strategies that actually parse this language
- [ ] fixture repo with deliberately-imperfect code + passing tests
- [ ] an end-to-end cycle test showing: consent honoured, patch emitted,
      fixture tree never mutated in place
