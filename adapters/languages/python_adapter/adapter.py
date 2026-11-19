"""Python language adapter: AST-based edits, pytest/unittest detection."""

from __future__ import annotations

from pathlib import Path

from loop.edits import MutationResult
from adapters.base import LanguageAdapter
from strategies.unused_imports import mutate as unused_imports
from strategies.strip_debug import mutate as strip_debug
from strategies.modernize_super import mutate as modernize_super


class PythonAdapter(LanguageAdapter):
    name = "python"

    def file_suffixes(self) -> list[str]:
        return [".py"]

    def strategies(self) -> dict[str, object]:
        return {
            "unused-imports": unused_imports,
            "strip-debug": strip_debug,
            "modernize-super": modernize_super,
        }

    def detect_test_command(self, worktree: Path) -> list[str] | None:
        wt = Path(worktree)
        has_pytest_ini = any(
            (wt / f).is_file() for f in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
        )
        has_test_files = any(True for _ in wt.rglob("test_*.py"))
        looks_pytest = (wt / "tests").is_dir() and has_test_files
        if has_pytest_ini and looks_pytest:
            return ["python", "-m", "pytest", "-q", "--no-header"]
        if has_test_files:
            # unittest discovery works without third-party deps
            return ["python", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"]
        return None
