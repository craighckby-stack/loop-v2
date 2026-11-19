"""Strategy: remove unused imports (per-file, conservative).

An import is "unused" when its bound name never appears as a Load anywhere
else in the module — including inside ``__all__``, strings of ``getattr``-style
dynamic use are NOT counted (fail-safe: keep the import).

Known-safe exceptions (never removed):
  * ``__init__.py`` entirely (implicit re-exports are invisible to static
    analysis; a false positive here breaks downstream imports)
  * ``import`` inside ``try:`` / ``except ImportError:`` (feature detection)
  * ``from __future__ import ...``
  * imports whose names appear in ``__all__``
  * star imports (can't bind a name to check)
"""

from __future__ import annotations

import ast
from pathlib import Path

from loop.edits import Edit, MutationResult
from strategies.common import apply_edits, parse_module


def _bound_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [a.asname or a.name for a in node.names]
    return []


def _inside_try_importguard(node: ast.stmt, tree: ast.Module) -> bool:
    """True if this import sits in a try-block that has an ImportError handler."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            handlers = [
                h for h in n.handlers
                if h.type is None
                or (isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError"))
                or (isinstance(h.type, ast.Tuple) and any(
                    isinstance(t, ast.Name) and t.id in ("ImportError", "ModuleNotFoundError")
                    for t in h.type.elts
                ))
            ]
            if handlers and node in n.body:
                return True
    return False


def propose_for_source(rel_path: str, source: str) -> list[Edit]:
    tree = parse_module(source)
    if tree is None:
        return []

    # collect every name loaded anywhere, and __all__ strings
    loaded: set[str] = set()
    dunder_all: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            loaded.add(n.id)
        if isinstance(n, ast.Attribute):
            pass  # attribute use covered by Name of the root object
        if (
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets)
            and isinstance(n.value, (ast.List, ast.Tuple))
        ):
            dunder_all.update(
                e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
            )

    edits: list[Edit] = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        if _inside_try_importguard(node, tree):
            continue
        if any(a.name == "*" for a in node.names):
            continue
        names = _bound_names(node)
        if not names:
            continue
        if any(name in dunder_all or name in loaded for name in names):
            continue  # some part is used (or re-exported): keep whole line
        # whole-statement removal; ranges are end-exclusive of node.end_lineno
        edits.append(
            Edit(
                file=rel_path,
                start_line=node.lineno,
                end_line=(node.end_lineno or node.lineno) + 1,
                new_text="",
                rationale=f"remove unused import(s): {', '.join(names)}",
            )
        )
    return edits


def mutate(worktree: Path, rel_files: list[str]) -> MutationResult:
    """Entry point registered in the Python adapter."""
    wt = Path(worktree)
    edits: list[Edit] = []
    for rel in rel_files:
        # never touch package __init__ files: implicit re-exports there are
        # legitimate public API, and static analysis cannot tell
        if Path(rel).name == "__init__.py":
            continue
        f = wt / rel
        try:
            source = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        edits.extend(propose_for_source(rel, source))
    if edits:
        apply_edits_to_worktree(wt, edits)
    return MutationResult(strategy="unused-imports", edits=edits)


def apply_edits_to_worktree(wt: Path, edits: list[Edit]) -> None:
    from strategies.common import apply_edits as _apply

    by_file: dict[str, list[Edit]] = {}
    for e in edits:
        by_file.setdefault(e.file, []).append(e)
    for rel, file_edits in by_file.items():
        _apply(wt / rel, file_edits)
