"""Git client: everything the loop does to a repository happens through here.

Two providers:

* ``local``    – the working copy is a plain directory (already a git repo or
                 initialised as one); emission is a patch or a local branch.
* ``github``   – clone from the upstream repo, work on a branch, push to a
                 fork, open a PR via the REST API (needs LOOP_GH_TOKEN).

Every commit carries the tool trailers from ``loop.etiquette.commit_trailers``
so provenance survives the trip upstream.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from loop.etiquette import commit_trailers
from loop.config.target import TargetConfig
from loop import COMMIT_USER_EMAIL, COMMIT_USER_NAME


class GitError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


class GitClient:
    """Thin, explicit wrapper. No repo state is cached between calls."""

    def __init__(self, cfg: TargetConfig) -> None:
        self.cfg = cfg

    # ----------------------------------------------------------- acquisition

    def acquire(self, dest: Path) -> Path:
        """Materialise a clean working copy of the base branch at ``dest``."""
        dest = Path(dest)
        if dest.exists():
            raise GitError(f"working copy destination already exists: {dest}")
        if self.cfg.provider == "github":
            url = f"https://github.com/{self.cfg.repo}.git"
            _git(dest.parent, "clone", "--branch", self.cfg.base_branch, url, str(dest))
        else:
            src = Path(self.cfg.local_path or "")
            if not src.is_dir():
                raise GitError(f"local_path does not exist: {src}")
            # copy the tree (excluding .git) then init a fresh repo: the loop
            # never mutates the user's original checkout in place.
            subprocess.run(
                ["cp", "-a", str(src) + "/.", str(dest)], check=True, timeout=120
            )
            _git(dest, "init", "-q", "-b", self.cfg.base_branch)
            _git(dest, "add", "-A")
            # identity defaults matter here too: bare CI runners have no
            # global git identity, and this snapshot commit must succeed there
            proc = subprocess.run(
                ["git", "-C", str(dest), "commit", "-q", "--allow-empty",
                 "-m", "loop-v2: snapshot of local target"],
                capture_output=True, text=True, timeout=60,
                env=self._commit_env(),
            )
            if proc.returncode != 0:
                raise GitError(f"git commit failed: {proc.stderr.strip()}")
        _ = self.head_sha(dest)  # sanity: HEAD resolves (snapshot commit exists)
        return dest

    # ------------------------------------------------------------- plumbing

    def head_sha(self, wc: Path) -> str:
        return _git(wc, "rev-parse", "HEAD").stdout.strip()

    def status_clean(self, wc: Path) -> bool:
        return _git(wc, "status", "--porcelain").stdout.strip() == ""

    def create_branch(self, wc: Path, name: str) -> None:
        _git(wc, "checkout", "-q", "-b", name)

    def checkout_reset(self, wc: Path, sha: str) -> None:
        """Hard reset the working copy to ``sha``, discarding uncommitted
        or committed-but-rejected mutations. Used to revert failed strategies."""
        _git(wc, "checkout", "-q", "--force", sha, "--")
        _git(wc, "reset", "-q", "--hard", sha)
        _git(wc, "clean", "-qfd")

    #: untracked build/test artifacts that must never reach a commit; the
    #: gate's own test runs produce these inside the working copy
    _ARTIFACT_DIRS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".venv")
    _ARTIFACT_SUFFIXES = (".pyc", ".pyo", ".coverage", ".lock")

    def _scrub_artifacts(self, wc: Path) -> None:
        """Remove untracked cache files so 'git add -A' stays honest."""
        for p in list(Path(wc).rglob("*")):
            if not p.is_file():
                continue
            if any(seg in self._ARTIFACT_DIRS for seg in p.parts):
                p.unlink()
        for d in list(Path(wc).rglob("__pycache__")):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        for cache_dir in self._ARTIFACT_DIRS[1:]:
            d = Path(wc) / cache_dir
            if d.is_dir():
                import shutil

                shutil.rmtree(d, ignore_errors=True)

    @staticmethod
    def _commit_env() -> dict[str, str]:
        """Environment for commits: default identity so they work in
        CI/containers without a global git config; a configured user
        identity always wins."""
        env = os.environ.copy()
        env.setdefault("GIT_AUTHOR_NAME", COMMIT_USER_NAME)
        env.setdefault("GIT_AUTHOR_EMAIL", COMMIT_USER_EMAIL)
        env.setdefault("GIT_COMMITTER_NAME", COMMIT_USER_NAME)
        env.setdefault("GIT_COMMITTER_EMAIL", COMMIT_USER_EMAIL)
        return env

    def commit_all(self, wc: Path, message: str) -> None:
        self._scrub_artifacts(wc)
        _git(wc, "add", "-A")
        env = self._commit_env()
        trailer_args: list[str] = []
        for t in commit_trailers():
            trailer_args += ["--trailer", t]
        proc = subprocess.run(
            ["git", "-C", str(wc), "commit", "-q", "-m", message, *trailer_args],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if proc.returncode != 0:
            raise GitError(f"git commit failed: {proc.stderr.strip()}")

    def diff(self, wc: Path, base: str) -> str:
        self._scrub_artifacts(wc)
        return _git(wc, "diff", base).stdout

    def changed_files(self, wc: Path, base: str) -> list[str]:
        out = _git(wc, "diff", "--name-only", base).stdout.strip()
        return [l for l in out.splitlines() if l]

    # -------------------------------------------------------------- emission

    def emit_patch(self, wc: Path, base: str, out_file: Path) -> str:
        patch = self.diff(wc, base)
        Path(out_file).write_text(patch, encoding="utf-8")
        return str(out_file)

    def emit_branch(self, wc: Path, branch: str, base: str, backup_patch: Path) -> str:
        """Move the committed changes onto ``branch`` and write a backup patch.

        A branch is only durable as long as its working copy exists, so the
        caller must keep the working copy for this emission to mean anything;
        the backup patch is the belt to that braces (same content, portable).
        """
        _git(wc, "branch", "-q", branch)
        self.emit_patch(wc, base, backup_patch)
        return branch

    def emit_pr(
        self,
        wc: Path,
        branch: str,
        title: str,
        body: str,
    ) -> str:
        """Push branch to the fork (or same repo) and open a PR. Returns URL."""
        if self.cfg.provider != "github":
            raise GitError("emit_pr requires provider='github'")
        token = os.environ.get("LOOP_GH_TOKEN")
        if not token:
            raise GitError("LOOP_GH_TOKEN not set; cannot push or open a PR")

        push_target = self.cfg.fork or self.cfg.repo
        remote_url = f"https://x-access-token:{token}@github.com/{push_target}.git"
        _git(wc, "remote", "add", "loopfork", remote_url)
        _git(wc, "push", "-q", "loopfork", f"{branch}:{branch}")

        api = f"https://api.github.com/repos/{self.cfg.repo}/pulls"
        payload = json.dumps({"title": title, "head": f"{push_target.split('/')[0]}:{branch}", "base": self.cfg.base_branch, "body": body}).encode()
        req = urllib.request.Request(api, data=payload, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            raise GitError(f"PR creation failed ({e.code}): {e.read().decode()[:400]}") from e
        return data["html_url"]
