"""Shared helpers for AST-based strategies: safe, line-level edit application."""

from __future__ import annotations

import ast
from pathlib import Path

from loop.edits import Edit


def parse_module(source: str) -> ast.Module | None:
    """Parse, returning None on syntax errors (strategy then skips the file)."""
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def apply_edits(path: Path, edits: list[Edit]) -> None:
    """Apply ``edits`` to ``path`` in one pass.

    Edits are line-based (1-based, end-exclusive). Overlapping edits are a
    programming error in a strategy and raise. ``new_text`` is a replacement
    FOR THE LINES, not a raw string: it is normalised to end with exactly
    one newline so replaced lines never merge with following lines.
    """
    if not edits:
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    # sort by start_line desc so earlier indexes stay valid while splicing
    for e in sorted(edits, key=lambda e: e.start_line, reverse=True):
        if not (1 <= e.start_line <= e.end_line <= len(lines) + 1):
            raise ValueError(f"edit out of range in {path}: {e}")
        if e.new_text:
            replacement = e.new_text.rstrip("\n") + "\n"
            lines[e.start_line - 1 : e.end_line - 1] = [replacement]
        else:
            lines[e.start_line - 1 : e.end_line - 1] = []
    text = "".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def source_segment_or_none(node: ast.AST, source: str) -> str | None:
    """ast.get_source_segment that never raises."""
    try:
        return ast.get_source_segment(source, node)
    except Exception:
        return None
