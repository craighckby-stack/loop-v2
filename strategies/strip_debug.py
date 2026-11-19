"""Strategy: strip leftover debug statements.

Removes whole-line ``print(...)`` calls whose first argument is a string
starting with ``DEBUG``/``DBG`` (any case), and ``breakpoint()`` calls with
no arguments. It never touches:

  * prints inside ``if __name__ == "__main__"`` blocks
  * logging calls (those are production code)
  * files whose name suggests they are tests or fixtures (already excluded
    by target config anyway, double-checked here)

This is deliberately conservative: only unambiguous debug leftovers go.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from loop.edits import Edit, MutationResult
from strategies.common import apply_edits, parse_module


def _first_arg_text(first: ast.expr) -> str | None:
    """Literal text of a call's first argument; handles plain strings and
    f-strings whose leading literal chunk carries the debug prefix."""
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if isinstance(first, ast.JoinedStr) and first.values:
        head = first.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    return None


def _is_debug_print(call: ast.Call) -> bool:
    if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
        return False
    if not call.args:
        return False
    text = _first_arg_text(call.args[0])
    # only an unambiguous debug prefix ("DEBUG ", "DBG:", "dbg-x", ...)
    # counts; "debugging value ..." is normal output and is kept.
    if text is None:
        return False
    return re.match(r"^(debug|dbg)([\s:\-]|$)", text.lstrip(), re.IGNORECASE) is not None


def _is_bare_breakpoint(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "breakpoint"
        and not call.args
        and not call.keywords
    )


def _in_main_guard(node: ast.AST, tree: ast.Module) -> bool:
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__"
            and any(
                isinstance(c, ast.Constant) and c.value == "__main__"
                for c in n.test.comparators
            )
        ):
            if node in ast.walk(n):
                return True
    return False


def propose_for_source(rel_path: str, source: str) -> list[Edit]:
    tree = parse_module(source)
    if tree is None:
        return []
    edits: list[Edit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not (_is_debug_print(call) or _is_bare_breakpoint(call)):
            continue
        if _in_main_guard(node, tree):
            continue
        edits.append(
            Edit(
                file=rel_path,
                start_line=node.lineno,
                end_line=(node.end_lineno or node.lineno) + 1,
                new_text="",
                rationale="remove leftover debug statement",
            )
        )
    return edits


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
    return MutationResult(strategy="strip-debug", edits=edits)
