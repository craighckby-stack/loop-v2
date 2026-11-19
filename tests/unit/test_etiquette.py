"""Unit tests: etiquette guards (consent, blocklist, rate limits)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from loop.config import TargetConfig
from loop.etiquette import Blocklist, Consent, ConsentError, RateLimiter, check_all
from loop.provenance import ProvenanceLog


def _cfg(tmp_path: Path, **over) -> TargetConfig:
    body = """
[target]
id = "demo"
provider = "local"
local_path = "/tmp/somewhere"
max_prs_per_week = 2
max_runs_per_day = 2
"""
    f = tmp_path / "target.toml"
    f.write_text(body, encoding="utf-8")
    return TargetConfig.load(f)


def _wc_with_consent(tmp_path: Path, content: str | None) -> Path:
    wc = tmp_path / "wc"
    wc.mkdir(exist_ok=True)
    if content is not None:
        (wc / ".loop-consent").write_text(content, encoding="utf-8")
    return wc


class TestConsent:
    def test_missing_marker_refuses(self, tmp_path):
        wc = _wc_with_consent(tmp_path, None)
        assert Consent.from_working_copy(wc).consent is False
        with pytest.raises(ConsentError, match="opted in"):
            check_all(_cfg(tmp_path), wc, ProvenanceLog(tmp_path / "log"))

    def test_false_consent_refuses(self, tmp_path):
        wc = _wc_with_consent(tmp_path, "consent = false\n")
        with pytest.raises(ConsentError):
            check_all(_cfg(tmp_path), wc, ProvenanceLog(tmp_path / "log"))

    def test_malformed_marker_refuses(self, tmp_path):
        wc = _wc_with_consent(tmp_path, "consent = <<<broken")
        with pytest.raises(ConsentError):
            check_all(_cfg(tmp_path), wc, ProvenanceLog(tmp_path / "log"))

    def test_valid_consent_passes(self, tmp_path):
        wc = _wc_with_consent(tmp_path, 'consent = true\ncontact = "a@b.c"\n')
        c = check_all(_cfg(tmp_path), wc, ProvenanceLog(tmp_path / "log"))
        assert c.consent and c.contact == "a@b.c"

    def test_consent_tightens_weekly_cap(self, tmp_path):
        wc = _wc_with_consent(tmp_path, "consent = true\nmax_prs_per_week = 1\n")
        c = check_all(_cfg(tmp_path), wc, ProvenanceLog(tmp_path / "log"))
        assert c.max_prs_per_week == 1  # min(2 from config, 1 from consent)


class TestBlocklist:
    def test_exact_repo_blocked(self):
        bl = Blocklist(entries={"acme/widgets"})
        assert bl.blocked("acme/widgets") is True
        assert bl.blocked("acme/other") is False

    def test_owner_wildcard(self):
        bl = Blocklist(entries={"acme/*"})
        assert bl.blocked("acme/anything") is True

    def test_owner_alone_blocks_all_repos(self):
        bl = Blocklist(entries={"acme"})
        assert bl.blocked("acme/widgets") is True

    def test_case_insensitive(self):
        bl = Blocklist(entries={"ACME/Widgets"})
        assert bl.blocked("acme/widgets") is True

    def test_blocked_repo_refuses_even_with_consent(self, tmp_path):
        wc = _wc_with_consent(tmp_path, "consent = true\n")
        cfg = _cfg(tmp_path)
        with pytest.raises(ConsentError, match="blocklist"):
            # local provider is identified by its target id
            check_all(cfg, wc, ProvenanceLog(tmp_path / "log"), Blocklist(entries={"demo"}))

    def test_stop_keyword_in_provenance_blocks(self, tmp_path):
        wc = _wc_with_consent(tmp_path, "consent = true\n")
        log = ProvenanceLog(tmp_path / "log")
        log.append({"kind": "stop", "target_id": "demo", "repo": "x/y"})
        with pytest.raises(ConsentError, match="loop-stop"):
            check_all(_cfg(tmp_path), wc, log)


class TestRateLimiter:
    def _log_with(self, tmp_path, records):
        log = ProvenanceLog(tmp_path / "log")
        for r in records:
            log.append(r)
        return log

    def test_clean_slate_allows(self, tmp_path):
        log = self._log_with(tmp_path, [])
        ok, why = RateLimiter(log).check(_cfg(tmp_path), Consent(consent=True))
        assert ok and why == "ok"

    def test_weekly_cap_enforced(self, tmp_path):
        recs = [
            {"kind": "mutation", "target_id": "demo", "emitted": "p.patch", "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            {"kind": "mutation", "target_id": "demo", "emitted": "q.patch", "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        ]
        log = self._log_with(tmp_path, recs)
        ok, why = RateLimiter(log).check(_cfg(tmp_path), Consent(consent=True))
        assert not ok and "weekly" in why

    def test_daily_run_cap_enforced(self, tmp_path):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        recs = [
            {"kind": "run-start", "target_id": "demo", "ts": now},
            {"kind": "run-start", "target_id": "demo", "ts": now},
        ]
        log = self._log_with(tmp_path, recs)
        ok, why = RateLimiter(log).check(_cfg(tmp_path), Consent(consent=True))
        assert not ok and "daily" in why

    def test_consent_cap_overrides_config(self, tmp_path):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        recs = [{"kind": "mutation", "target_id": "demo", "emitted": "p.patch", "ts": now}]
        log = self._log_with(tmp_path, recs)
        ok, why = RateLimiter(log).check(_cfg(tmp_path), Consent(consent=True, max_prs_per_week=1))
        assert not ok and "1" in why
