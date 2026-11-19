"""Unit tests: GitHub REST path (emit_pr) with urlopen mocked — no network.

Also covers the git identity defaults and the branch emission plumbing that
don't need a full cycle.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from loop import COMMIT_USER_EMAIL, COMMIT_USER_NAME, TOOL_TRAILER
from loop.config import TargetConfig
from loop.gitclient import GitClient, GitError


def _gh_cfg(tmp_path: Path, emit: str = "pr", fork: str | None = None) -> TargetConfig:
    f = tmp_path / "target.toml"
    fork_line = f'\nfork = "{fork}"' if fork else ""
    f.write_text(
        f"""
[target]
id = "gh-demo"
provider = "github"
repo = "upstream/proj"{fork_line}
base_branch = "main"
emit = "{emit}"
""",
        encoding="utf-8",
    )
    return TargetConfig.load(f)


def _wc(tmp_path: Path) -> Path:
    """A tiny real git repo standing in for a working copy."""
    wc = tmp_path / "wc"
    wc.mkdir()
    # GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM=/dev/null: no user or system git
    # config exists, exactly like a bare CI container
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    subprocess.run(["git", "-C", str(wc), "init", "-q", "-b", "main"],
                   check=True, env=env)
    (wc / "f.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wc), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(wc), "-c", f"user.name={COMMIT_USER_NAME}",
         "-c", f"user.email={COMMIT_USER_EMAIL}",
         "commit", "-q", "-m", "init"],
        check=True, env=env,
    )
    return wc


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class TestEmitPr:
    def test_missing_token_refuses(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LOOP_GH_TOKEN", raising=False)
        client = GitClient(_gh_cfg(tmp_path))
        with pytest.raises(GitError, match="LOOP_GH_TOKEN"):
            client.emit_pr(_wc(tmp_path), "loop/x", "t", "b")

    def test_local_provider_refuses(self, tmp_path):
        f = tmp_path / "target.toml"
        f.write_text(
            """
[target]
id = "local-demo"
provider = "local"
local_path = "/tmp/nowhere"
""",
            encoding="utf-8",
        )
        client = GitClient(TargetConfig.load(f))
        with pytest.raises(GitError, match="provider='github'"):
            client.emit_pr(_wc(tmp_path), "loop/x", "t", "b")

    def test_pr_created_with_correct_payload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOP_GH_TOKEN", "tok-123")
        client = GitClient(_gh_cfg(tmp_path))
        wc = _wc(tmp_path)

        captured: dict = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["headers"] = dict(req.header_items())
            captured["payload"] = json.loads(req.data.decode())
            return _Resp({"html_url": "https://github.com/upstream/proj/pull/7"})

        # no remote 'loopfork' yet: emit_pr adds it; stub the push away
        def fake_git_push(cwd, *args, **kw):
            class P:
                returncode = 0
                stdout = ""
                stderr = ""
            return P()

        monkeypatch.setattr("loop.gitclient.client.urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("loop.gitclient.client._git", fake_git_push)

        url = client.emit_pr(wc, "loop/run-1", "loop-v2: test", "body text")
        assert url == "https://github.com/upstream/proj/pull/7"
        assert captured["url"] == "https://api.github.com/repos/upstream/proj/pulls"
        assert captured["method"] == "POST"
        assert captured["payload"]["title"] == "loop-v2: test"
        assert captured["payload"]["head"] == "upstream:loop/run-1"
        assert captured["payload"]["base"] == "main"
        assert "Bearer tok-123" in captured["headers"].get("Authorization", "")

    def test_fork_used_for_head_and_push(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOP_GH_TOKEN", "tok-123")
        client = GitClient(_gh_cfg(tmp_path, fork="me/proj-fork"))
        wc = _wc(tmp_path)
        captured: dict = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data.decode())
            return _Resp({"html_url": "https://github.com/upstream/proj/pull/8"})

        def fake_git(cwd, *args, **kw):
            class P:
                returncode = 0
                stdout = ""
                stderr = ""
            if args and args[0] == "remote":
                captured["remote_url"] = args[-1]
            return P()

        monkeypatch.setattr("loop.gitclient.client.urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("loop.gitclient.client._git", fake_git)

        client.emit_pr(wc, "loop/run-2", "t", "b")
        assert captured["payload"]["head"] == "me:loop/run-2"
        assert "me/proj-fork" in captured["remote_url"]

    def test_http_error_surfaced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOP_GH_TOKEN", "tok-123")
        client = GitClient(_gh_cfg(tmp_path))
        wc = _wc(tmp_path)

        def fake_git(cwd, *args, **kw):
            class P:
                returncode = 0
                stdout = ""
                stderr = ""
            return P()

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 422, "Unprocessable", {}, None
            )

        monkeypatch.setattr("loop.gitclient.client._git", fake_git)
        monkeypatch.setattr("loop.gitclient.client.urllib.request.urlopen", fake_urlopen)
        with pytest.raises(GitError, match="422"):
            client.emit_pr(wc, "loop/run-3", "t", "b")


class TestCommitIdentity:
    def test_commit_works_without_global_git_config(self, tmp_path, monkeypatch):
        """The default identity must let commits succeed in a bare env (CI)."""
        client = GitClient(_gh_cfg(tmp_path, emit="patch"))
        wc = _wc(tmp_path)
        (wc / "g.txt").write_text("change\n", encoding="utf-8")
        # scrub HOME so no user git config can exist
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        (tmp_path / "empty-home").mkdir(exist_ok=True)
        client.commit_all(wc, "loop-v2: change something")
        log = subprocess.run(
            ["git", "-C", str(wc), "log", "-1", "--format=%an <%ae>"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert log == f"{COMMIT_USER_NAME} <{COMMIT_USER_EMAIL}>"
        # the tool trailer must be on the commit
        body = subprocess.run(
            ["git", "-C", str(wc), "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert TOOL_TRAILER.split(":")[0] + ":" in body
