"""Shared pytest fixtures: import the repo root, build scratch dirs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def tmp_tree(tmp_path: Path) -> Path:
    return tmp_path
