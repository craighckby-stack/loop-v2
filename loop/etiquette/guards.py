"""Etiquette layer: consent, blocklist, rate limits, kill switch.

These are guard rails, not options. ``check_all`` must pass before the
orchestrator is allowed to touch a working copy, and every cycle re-checks.

Consent model
-------------
A repo consents by containing a marker file at its default branch root:

    .loop-consent

whose content is TOML:

    consent = true
    contact = "you@example.com"        # optional but recommended
    max_prs_per_week = 3               # optional, tightens the target limit

If the file is missing, or says ``consent = false``, the loop refuses to run.
Upstream maintainers can also kill the loop for their repo by replying to
any emitted PR with the keyword ``loop-stop`` (recorded in the blocklist)
or simply by deleting the marker file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loop import STOP_KEYWORD, TOOL_NAME
from loop.config.target import TargetConfig
from loop.provenance.log import ProvenanceLog

CONSENT_FILENAME = ".loop-consent"


class ConsentError(RuntimeError):
    """Raised when a target has not opted in or is blocked."""


@dataclass
class Consent:
    consent: bool
    contact: str | None = None
    max_prs_per_week: int | None = None
    source: str = "missing"

    @classmethod
    def from_working_copy(cls, wc: Path) -> "Consent":
        """Read the consent marker from a checked-out working copy."""
        f = Path(wc) / CONSENT_FILENAME
        if not f.is_file():
            return cls(consent=False, source="missing")
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return cls(consent=False, source="malformed")
        return cls(
            consent=bool(data.get("consent", False)),
            contact=data.get("contact"),
            max_prs_per_week=data.get("max_prs_per_week"),
            source="file",
        )


@dataclass
class Blocklist:
    """Repositories and owners the tool must never touch.

    Ships with the tool (``BLOCKLIST``) and is user-extendable via a local
    ``blocklist.txt`` (one 'owner/name', 'owner' or 'owner/*' per line).
    ``loop-stop`` replies recorded in provenance are honoured too.
    """

    entries: set[str] = field(default_factory=set)

    #: Conservative default: these orgs have publicly asked autonomous PR
    #: bots to stay away (extend as maintainers request it).
    DEFAULT_ENTRIES: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        # blocklist matching is case-insensitive everywhere
        self.entries = {e.lower() for e in self.entries}

    @classmethod
    def load(cls, extra_file: Path | None = None) -> "Blocklist":
        entries = {e.lower() for e in cls.DEFAULT_ENTRIES}
        if extra_file and Path(extra_file).is_file():
            for line in Path(extra_file).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    entries.add(line.lower())
        return cls(entries=entries)

    def blocked(self, repo: str) -> bool:
        """True if 'owner/name' matches a blocked owner, repo or wildcard."""
        repo = repo.lower()
        if repo in self.entries:
            return True
        owner = repo.split("/", 1)[0]
        if owner in self.entries or f"{owner}/*" in self.entries:
            return True
        return False

    def add_stop(self, repo: str) -> None:
        """Record a 'loop-stop' request: this repo is now permanently blocked."""
        self.entries.add(repo.lower())


class RateLimiter:
    """Per-target sliding-window limiter over the provenance log.

    Two windows: emitted PRs per ISO week (counting 'mutation' records with
    an emission) and runs per calendar day (counting 'run-start' records).
    The tighter of the target config and the consent file always wins.
    """

    def __init__(self, log: ProvenanceLog) -> None:
        self.log = log

    def _iso_week_key(self, ts: str) -> str:
        d = datetime.strptime(ts[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"

    def prs_this_week(self, target_id: str, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        key = self._iso_week_key(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        n = 0
        for r in self.log.records_for_target(target_id):
            if r.get("kind") != "mutation" or not r.get("emitted"):
                continue
            if self._iso_week_key(r.get("ts", "")) == key:
                n += 1
        return n

    def runs_today(self, target_id: str, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        n = 0
        for r in self.log.records_for_target(target_id):
            if r.get("kind") == "run-start" and r.get("ts", "")[:10] == today:
                n += 1
        return n

    def check(
        self,
        cfg: TargetConfig,
        consent: Consent,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        now = now or datetime.now(timezone.utc)
        weekly_cap = cfg.max_prs_per_week
        if consent.max_prs_per_week is not None:
            weekly_cap = min(weekly_cap, consent.max_prs_per_week)
        if self.prs_this_week(cfg.target_id, now) >= weekly_cap:
            return False, f"weekly PR cap reached ({weekly_cap})"
        if self.runs_today(cfg.target_id, now) >= cfg.max_runs_per_day:
            return False, f"daily run cap reached ({cfg.max_runs_per_day})"
        return True, "ok"


def check_all(
    cfg: TargetConfig,
    working_copy: Path,
    log: ProvenanceLog,
    blocklist: Blocklist | None = None,
) -> Consent:
    """Full pre-flight etiquette check. Raises ConsentError on refusal.

    Returns the parsed Consent so callers can tighten rate limits.
    """
    blocklist = blocklist or Blocklist.load()
    # github targets are identified by 'owner/name'; local targets by their id
    identity = cfg.repo or cfg.target_id
    if blocklist.blocked(identity):
        raise ConsentError(
            f"{identity!r} is on the blocklist; {TOOL_NAME} refuses to run. "
            f"If this is wrong, remove the entry and the consent marker still governs."
        )

    # 'loop-stop' keyword recorded against this repo in provenance = permanent stop.
    for r in log.records_for_target(cfg.target_id):
        if r.get("kind") == "stop":
            raise ConsentError(
                f"a maintainer replied '{STOP_KEYWORD}' for {cfg.repo!r}; "
                "this repo is permanently blocked from this tool."
            )

    consent = Consent.from_working_copy(working_copy)
    if not consent.consent:
        raise ConsentError(
            f"{identity!r} has no valid {CONSENT_FILENAME} marker on its base branch "
            f"(found: {consent.source}). The loop only runs on repos that opted in: "
            "ask the maintainers to commit the marker file, see docs/etiquette.md."
        )
    return consent


def commit_trailers() -> list[str]:
    """Git trailers added to every commit the tool makes."""
    from loop import TOOL_TRAILER

    return [TOOL_TRAILER, "X-Loop-Stop: reply 'loop-stop' to make this tool never touch this repo again"]
