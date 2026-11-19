"""Unit tests: target.toml loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loop.config import TargetConfig, TargetConfigError


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "target.toml"
    f.write_text(body, encoding="utf-8")
    return f


MINIMAL_LOCAL = """
[target]
id = "demo"
provider = "local"
local_path = "/tmp/somewhere"
"""


def test_minimal_local_config(tmp_path):
    cfg = TargetConfig.load(_write(tmp_path, MINIMAL_LOCAL))
    assert cfg.target_id == "demo"
    assert cfg.provider == "local"
    assert cfg.emit == "patch"
    assert "unused-imports" in cfg.strategies
    assert cfg.max_prs_per_week == 3


def test_github_repo_format_enforced(tmp_path):
    body = """
[target]
id = "demo"
provider = "github"
repo = "not-a-valid-repo"
"""
    with pytest.raises(TargetConfigError, match="owner/name"):
        TargetConfig.load(_write(tmp_path, body))


def test_local_needs_path(tmp_path):
    body = """
[target]
id = "demo"
provider = "local"
"""
    with pytest.raises(TargetConfigError, match="local_path"):
        TargetConfig.load(_write(tmp_path, body))


def test_bad_emit_rejected(tmp_path):
    body = MINIMAL_LOCAL + '\nemit = "carrier-pigeon"\n'
    # emit lives inside [target]; append properly
    body = MINIMAL_LOCAL.replace('local_path = "/tmp/somewhere"', 'local_path = "/tmp/somewhere"\nemit = "carrier-pigeon"')
    with pytest.raises(TargetConfigError, match="emit"):
        TargetConfig.load(_write(tmp_path, body))


def test_id_must_be_kebab(tmp_path):
    body = MINIMAL_LOCAL.replace('id = "demo"', 'id = "Demo!"')
    with pytest.raises(TargetConfigError, match="kebab"):
        TargetConfig.load(_write(tmp_path, body))


def test_pr_emit_needs_github(tmp_path):
    body = MINIMAL_LOCAL.replace(
        'local_path = "/tmp/somewhere"',
        'local_path = "/tmp/somewhere"\nemit = "pr"',
    )
    with pytest.raises(TargetConfigError, match="pr"):
        TargetConfig.load(_write(tmp_path, body))


def test_matches_include_exclude(tmp_path):
    cfg = TargetConfig.load(_write(tmp_path, MINIMAL_LOCAL))
    assert cfg.matches("pkg/core.py")
    assert not cfg.matches("tests/test_core.py")
    assert not cfg.matches("docs/conf.py")
    assert not cfg.matches("README.md")
