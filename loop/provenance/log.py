"""Write-once provenance log (JSONL).

Every run appends one record per attempted mutation with: run id, target id,
upstream commit, strategy, files touched, gate verdict and emitted artifact.
Nothing is ever rewritten or deleted; ``report`` only reads.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from loop import TOOL_NAME, TOOL_VERSION


def new_run_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


class ProvenanceLog:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / "provenance.jsonl"

    def append(self, record: dict) -> dict:
        """Append one record; fills id/timestamp if missing. Returns the record."""
        rec = dict(record)
        rec.setdefault("record_id", uuid.uuid4().hex[:12])
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.path.open("a", encoding="utf-8").write(
            json.dumps(rec, sort_keys=True, default=str) + "\n"
        )
        return rec

    def run_record(
        self,
        *,
        run_id: str,
        target_id: str,
        upstream: str,
        base_branch: str,
        strategies: list[str],
        started_by: str,
    ) -> dict:
        """Convenience wrapper for the run-start record."""
        return self.append(
            {
                "kind": "run-start",
                "run_id": run_id,
                "target_id": target_id,
                "upstream": upstream,
                "base_branch": base_branch,
                "strategies": strategies,
                "started_by": started_by,
                "tool": f"{TOOL_NAME}/{TOOL_VERSION}",
            }
        )

    def mutation_record(
        self,
        *,
        run_id: str,
        target_id: str,
        upstream: str,
        strategy: str,
        files: list[str],
        gate: str,
        verdict: str,
        detail: str,
        emitted: str | None = None,
    ) -> dict:
        """Convenience wrapper for one mutation attempt."""
        return self.append(
            {
                "kind": "mutation",
                "run_id": run_id,
                "target_id": target_id,
                "upstream": upstream,
                "strategy": strategy,
                "files": files,
                "gate": gate,
                "verdict": verdict,          # pass | fail | error | skipped
                "detail": detail,
                "emitted": emitted,           # patch path / branch / PR url
            }
        )

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def records_for_target(self, target_id: str) -> list[dict]:
        return [r for r in self.records() if r.get("target_id") == target_id]
