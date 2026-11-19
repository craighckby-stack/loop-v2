"""Leaf data model shared by adapters and strategies.

This module imports NOTHING from the project so both ``adapters`` and
``strategies`` can use it without creating import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Edit:
    """One proposed textual change to one file (line ranges are 1-based,
    end-exclusive, matching Python's ``range`` semantics over file lines)."""

    file: str                 # repo-relative path, POSIX separators
    start_line: int           # first line to replace
    end_line: int             # line AFTER the last replaced line
    new_text: str             # replacement (may be "" for a deletion)
    rationale: str = ""       # human-readable why, ends up in the PR body


@dataclass
class MutationResult:
    """What a strategy produced for one file (or many)."""

    strategy: str
    edits: list[Edit] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.edits
