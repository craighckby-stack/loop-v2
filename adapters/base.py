"""Language adapter contract.

An adapter teaches the engine about ONE language: which files it owns, how
to make structurally-safe edits, and what counts as a runnable test command.
Everything else in the engine is language-agnostic.

To add a language, subclass :class:`LanguageAdapter` and register it in
``adapters/languages/registry.py``. See docs/adding-a-language-adapter.md.
"""

from __future__ import annotations

import abc
from pathlib import Path

from loop.edits import Edit, MutationResult  # leaf module, no cycles


class LanguageAdapter(abc.ABC):
    """One language. Stateless; safe to share across runs."""

    name: str = "?"

    @abc.abstractmethod
    def file_suffixes(self) -> list[str]:
        """Suffixes this adapter claims, e.g. ``[".py"]``."""

    @abc.abstractmethod
    def strategies(self) -> dict[str, object]:
        """strategy-id -> callable(worktree_path, rel_files) -> MutationResult.

        Returning the callables (from the ``strategies/`` package) here keeps
        the engine free of language-specific imports. Import lazily inside
        the method to avoid import cycles (strategies import the leaf
        ``loop.edits`` model only).
        """

    @abc.abstractmethod
    def detect_test_command(self, worktree: Path) -> list[str] | None:
        """Best-effort: the command that runs this language's tests in
        ``worktree``, or None if no test runner is detected. The gate falls
        back to 'no tests found' which fails closed (mutation cannot pass)."""

    def owns(self, rel_path: str) -> bool:
        return any(rel_path.endswith(sfx) for sfx in self.file_suffixes())
