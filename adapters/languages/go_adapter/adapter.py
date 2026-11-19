"""Go language adapter: file discovery and `go test` detection.

Phase 2 groundwork: the adapter teaches the engine where Go code lives and
how Go repos run their own tests. No mutation strategies ship yet — the
strategy dict is empty, so every configured strategy records 'skipped' and
nothing is mutated until a Go strategy is written (see
docs/adding-a-strategy.md; go/ast + go/format are the right tools).
"""

from __future__ import annotations

from pathlib import Path

from adapters.base import LanguageAdapter


class GoAdapter(LanguageAdapter):
    name = "go"

    def file_suffixes(self) -> list[str]:
        return [".go"]

    def strategies(self) -> dict[str, object]:
        # none yet: adapter brings discovery + gate, mutations come later
        return {}

    def detect_test_command(self, worktree: Path) -> list[str] | None:
        """`go test ./...` when the tree is a Go module with test files."""
        wt = Path(worktree)
        if not (wt / "go.mod").is_file():
            return None
        has_go_tests = any(True for _ in wt.rglob("*_test.go"))
        if not has_go_tests:
            return None
        return ["go", "test", "./..."]
