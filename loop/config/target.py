"""Target configuration: the one file that describes what the loop may do.

A target bundle is a directory containing ``target.toml`` (+ optional notes).
Nothing else in the engine hardcodes anything about a specific repository.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")

DEFAULT_LANGUAGES = ["python"]
DEFAULT_STRATEGIES = ["unused-imports", "strip-debug", "modernize-super"]
DEFAULT_INCLUDE = ["**/*.py"]
DEFAULT_EXCLUDE = ["**/tests/**", "**/test_*.py", "**/.venv/**", "**/docs/**"]


class TargetConfigError(ValueError):
    """Raised when a target.toml is malformed or unsafe."""


@dataclass
class TargetConfig:
    """Validated view of one target.toml."""

    target_id: str
    repo: str                      # "owner/name" on the git provider
    provider: str                  # "github" | "local"
    fork: str | None = None        # "owner/name" to push to (defaults: same repo, branch)
    base_branch: str = "main"
    branch_prefix: str = "loop/"
    languages: list[str] = field(default_factory=lambda: ["python"])
    strategies: list[str] = field(
        default_factory=lambda: ["unused-imports", "strip-debug", "modernize-super"]
    )
    include: list[str] = field(default_factory=lambda: ["**/*.py"])
    exclude: list[str] = field(
        default_factory=lambda: ["**/tests/**", "**/test_*.py", "**/.venv/**", "**/docs/**"]
    )
    max_prs_per_week: int = 3
    max_runs_per_day: int = 2
    require_clean_gate: bool = True
    emit: str = "patch"            # "patch" | "branch" | "pr"
    # --- local provider only ---
    local_path: str | None = None

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: Path) -> "TargetConfig":
        path = Path(path)
        if not path.is_file():
            raise TargetConfigError(f"target config not found: {path}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise TargetConfigError(f"invalid TOML in {path}: {e}") from e

        meta = raw.get("target", {})
        if not isinstance(meta, dict):
            raise TargetConfigError(f"{path}: [target] table missing or not a table")

        provider = str(meta.get("provider", "local"))
        cfg = cls(
            target_id=str(meta.get("id", path.parent.name)),
            provider=provider,
            repo=str(meta.get("repo", "")),
            fork=meta.get("fork"),
            base_branch=str(meta.get("base_branch", "main")),
            branch_prefix=str(meta.get("branch_prefix", "loop/")),
            languages=[str(x) for x in meta.get("languages", DEFAULT_LANGUAGES)],
            strategies=[str(x) for x in meta.get("strategies", DEFAULT_STRATEGIES)],
            include=[str(x) for x in meta.get("include", DEFAULT_INCLUDE)],
            exclude=[str(x) for x in meta.get("exclude", DEFAULT_EXCLUDE)],
            max_prs_per_week=int(meta.get("max_prs_per_week", 3)),
            max_runs_per_day=int(meta.get("max_runs_per_day", 2)),
            require_clean_gate=bool(meta.get("require_clean_gate", True)),
            emit=str(meta.get("emit", "patch")),
            local_path=meta.get("local_path"),
        )
        cfg._validate(path)
        return cfg

    # -------------------------------------------------------------- validate

    def _validate(self, path: Path) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*", self.target_id):
            raise TargetConfigError(
                f"{path}: target id '{self.target_id}' must be lowercase kebab-case"
            )
        if self.provider not in ("github", "local"):
            raise TargetConfigError(f"{path}: provider must be 'github' or 'local'")
        if self.provider == "github":
            if not _REPO_RE.fullmatch(self.repo or ""):
                raise TargetConfigError(
                    f"{path}: [target] repo must look like 'owner/name', got {self.repo!r}"
                )
            if self.fork is not None and not _REPO_RE.fullmatch(self.fork):
                raise TargetConfigError(f"{path}: [target] fork must look like 'owner/name'")
        else:
            if not self.local_path:
                raise TargetConfigError(
                    f"{path}: local provider requires 'local_path' under [target]"
                )
        if not self.strategies:
            raise TargetConfigError(f"{path}: at least one strategy must be enabled")
        if not self.languages:
            raise TargetConfigError(f"{path}: at least one language must be listed")
        if self.emit not in ("patch", "branch", "pr"):
            raise TargetConfigError(f"{path}: emit must be 'patch', 'branch' or 'pr'")
        if self.emit == "pr" and self.provider == "local":
            raise TargetConfigError(f"{path}: emit='pr' needs provider='github'")
        if self.max_prs_per_week < 1 or self.max_prs_per_day_limit_ok() is False:
            raise TargetConfigError(f"{path}: rate limits must be >= 1")
        if not self.branch_prefix.endswith("/") and self.branch_prefix != "":
            # normalise but keep it strict: prefix must end with '/'
            self.branch_prefix += "/"

    def max_prs_per_day_limit_ok(self) -> bool:
        return self.max_runs_per_day >= 1

    # -------------------------------------------------------------- helpers

    def matches(self, rel_path: str) -> bool:
        """True if a repo-relative path is in scope for mutation."""
        from fnmatch import fnmatch

        posix = rel_path.replace("\\", "/")
        if not any(fnmatch(posix, pat) for pat in self.include):
            return False
        if any(fnmatch(posix, pat) for pat in self.exclude):
            return False
        # fnmatch has no path-segment semantics: '**/docs/**' must also
        # exclude 'docs/...' (no leading segment), so test dir prefixes too.
        for pat in self.exclude:
            segs = [s for s in pat.split("/") if s and s != "**"]
            if segs and posix.startswith(segs[0] + "/"):
                return False
            if any("/" + s + "/" in "/" + posix for s in segs):
                return False
        return True
