"""Strategy: modernise old-style ``super(...)`` calls.

``class Foo(Bar):`` + ``Bar.__init__(self, ...)`` inside a method of Foo
becomes ``super().__init__(...)``. Only rewritten when:

  * the enclosing class has exactly one base (MRO is unambiguous),
  * the attribute call is on that exact base class name,
  * the first positional argument is the ``self`` of the enclosing method,
  * and the call is an Expression-statement or the sole expression of a
    return (the two forms where the value is discarded or passed through).

Line-level edit with exact source reuse; if the call spans multiple lines
the edit is skipped (keeps diffs simple and reviewable).
"""

from __future__ import annotations

import ast
from pathlib import Path

from loop.edits import Edit, MutationResult
from strategies.common import apply_edits, parse_module


def propose_for_source(rel_path: str, source: str) -> list[Edit]:
    tree = parse_module(source)
    if tree is None:
        return []
    lines = source.splitlines()
    edits: list[Edit] = []

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        if len(cls.bases) != 1 or not isinstance(cls.bases[0], ast.Name):
            continue
        base_name = cls.bases[0].id

        for func in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            self_name = func.args.args[0].arg if func.args.args else None
            if not self_name:
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if not (isinstance(f, ast.Attribute) and f.attr != "__class__"):
                    continue
                if not (isinstance(f.value, ast.Name) and f.value.id == base_name):
                    continue
                if not (node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == self_name):
                    continue
                # single-line calls only, and the statement must be an Expr
                if node.lineno != (node.end_lineno or node.lineno):
                    continue
                is_expr_stmt = any(
                    isinstance(p, ast.Expr) and p.value is node
                    for p in ast.walk(func)
                )
                if not is_expr_stmt:
                    continue
                line = lines[node.lineno - 1]
                before = line[: node.col_offset]
                # rebuild: super().attr(rest...)
                call_segment = line[node.col_offset :]
                rest = _strip_base_and_self(call_segment, base_name, self_name, f.attr)
                if rest is None:
                    continue
                new_text = f"{before}super().{f.attr}({rest}"
                edits.append(
                    Edit(
                        file=rel_path,
                        start_line=node.lineno,
                        end_line=node.lineno + 1,
                        new_text=new_text,
                        rationale=f"use super() instead of {base_name}.{f.attr}(self, ...)",
                    )
                )
    return edits


def _strip_base_and_self(segment: str, base: str, self_name: str, attr: str) -> str | None:
    """Given 'Base.attr(self, x)' return 'x)' (contents after self, + ')')."""
    prefix = f"{base}.{attr}({self_name}"
    idx = segment.find(prefix)
    if idx == -1:
        return None
    rest = segment[idx + len(prefix):]
    if rest.startswith(","):
        return rest[1:].lstrip()
    if rest.startswith(")"):
        return ")"
    return None


def mutate(worktree: Path, rel_files: list[str]) -> MutationResult:
    wt = Path(worktree)
    edits: list[Edit] = []
    for rel in rel_files:
        f = wt / rel
        try:
            source = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        edits.extend(propose_for_source(rel, source))
    by_file: dict[str, list[Edit]] = {}
    for e in edits:
        by_file.setdefault(e.file, []).append(e)
    for rel, file_edits in by_file.items():
        apply_edits(wt / rel, file_edits)
    return MutationResult(strategy="modernize-super", edits=edits)
