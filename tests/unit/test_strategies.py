"""Unit tests: the three AST strategies, on real source strings."""

from __future__ import annotations

import textwrap
from pathlib import Path

from strategies.modernize_super import propose_for_source as super_edits
from strategies.strip_debug import propose_for_source as debug_edits
from strategies.unused_imports import propose_for_source as import_edits
from strategies.common import apply_edits


def _apply(src: str, edits) -> str:
    assert edits, "expected at least one edit"
    f = Path("/tmp/_strategy_unit_test.py")
    f.write_text(textwrap.dedent(src), encoding="utf-8")
    apply_edits(f, edits)
    return f.read_text(encoding="utf-8")


class TestUnusedImports:
    def test_removes_unused(self):
        src = """
        import json
        import os
        x = 1
        """
        edits = import_edits("m.py", textwrap.dedent(src))
        assert [e.rationale for e in edits] and len(edits) == 2
        out = _apply(src, edits)
        assert "import json" not in out and "import os" not in out
        assert "x = 1" in out

    def test_keeps_used(self):
        src = """
        import json
        x = json.dumps({})
        """
        assert import_edits("m.py", textwrap.dedent(src)) == []

    def test_keeps_dunder_all_reexport(self):
        src = """
        import json
        __all__ = ["json"]
        """
        assert import_edits("m.py", textwrap.dedent(src)) == []

    def test_keeps_future(self):
        src = """
        from __future__ import annotations
        x = 1
        """
        assert import_edits("m.py", textwrap.dedent(src)) == []

    def test_keeps_try_import_guard(self):
        src = """
        try:
    import ujson as json
        except ImportError:
    import json
        """
        assert import_edits("m.py", textwrap.dedent(src)) == []

    def test_partial_use_keeps_line(self):
        src = """
        import os, sys
        p = os.getcwd()
        """
        # sys unused but os used: whole line must stay
        assert import_edits("m.py", textwrap.dedent(src)) == []

    def test_syntax_error_skipped(self):
        assert import_edits("m.py", "def broken(:\n") == []


class TestStripDebug:
    def test_removes_debug_print(self):
        src = """
        def f():
            print("DEBUG reached f")
            return 1
        """
        edits = debug_edits("m.py", textwrap.dedent(src))
        assert len(edits) == 1
        out = _apply(src, edits)
        assert "DEBUG" not in out and "return 1" in out

    def test_keeps_normal_print(self):
        src = """
        def f():
            print("hello user")
        """
        assert debug_edits("m.py", textwrap.dedent(src)) == []

    def test_removes_bare_breakpoint(self):
        src = """
        def f():
            breakpoint()
        """
        edits = debug_edits("m.py", textwrap.dedent(src))
        assert len(edits) == 1

    def test_keeps_main_guard(self):
        src = """
        if __name__ == "__main__":
            print("DEBUG boot")
        """
        assert debug_edits("m.py", textwrap.dedent(src)) == []

    def test_keeps_print_with_args(self):
        src = """
        def f(x):
            print("debugging value", x)
        """
        assert debug_edits("m.py", textwrap.dedent(src)) == []


class TestModernizeSuper:
    def test_rewrites_old_super(self):
        src = """
        class A:
            def __init__(self, x):
                self.x = x

        class B(A):
            def __init__(self, x, y):
                A.__init__(self, x)
                self.y = y
        """
        edits = super_edits("m.py", textwrap.dedent(src))
        assert len(edits) == 1
        out = _apply(src, edits)
        assert "super().__init__(x)" in out
        assert "A.__init__" not in out

    def test_wrong_base_not_touched(self):
        src = """
        class A:
            def __init__(self): pass
        class Unrelated:
            pass
        class B(A):
            def __init__(self):
                Unrelated.__init__(self)
        """
        assert super_edits("m.py", textwrap.dedent(src)) == []

    def test_multi_base_class_skipped(self):
        src = """
        class A:
            def __init__(self): pass
        class C:
            def __init__(self): pass
        class B(A, C):
            def __init__(self):
                A.__init__(self)
        """
        assert super_edits("m.py", textwrap.dedent(src)) == []

    def test_method_call_not_stmt_skipped(self):
        # A.__init__(self) used as an expression (assigned) is left alone
        src = """
        class A:
            def m(self): return 1
        class B(A):
            def __init__(self):
                r = A.m(self)
        """
        assert super_edits("m.py", textwrap.dedent(src)) == []
