"""Eval gates: the modules that decide whether a mutation ships.

Currently one gate: run the repo's own test command before/after
(the repo's CI semantics are the eval — this tool imposes none of its own).
"""
from gates.test_gate import GateRun, baseline, evaluate

__all__ = ["GateRun", "baseline", "evaluate"]
