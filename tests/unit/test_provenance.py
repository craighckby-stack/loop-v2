"""Unit tests: provenance log write-once semantics and rate queries."""

from __future__ import annotations

import json
from pathlib import Path

from loop.provenance import ProvenanceLog, new_run_id


def test_append_and_read_roundtrip(tmp_path: Path):
    log = ProvenanceLog(tmp_path)
    log.run_record(run_id="r1", target_id="t", upstream="abc", base_branch="main",
                   strategies=["s"], started_by="cli")
    log.mutation_record(run_id="r1", target_id="t", upstream="abc", strategy="s",
                        files=["a.py"], gate="test-gate", verdict="pass", detail="ok",
                        emitted="out.patch")
    recs = log.records()
    assert len(recs) == 2
    assert recs[0]["kind"] == "run-start"
    assert recs[1]["verdict"] == "pass"
    # every record carries generated ids/timestamps
    assert recs[0]["record_id"] and recs[0]["ts"]


def test_records_filter_by_target(tmp_path: Path):
    log = ProvenanceLog(tmp_path)
    log.append({"kind": "mutation", "target_id": "t1", "emitted": "x"})
    log.append({"kind": "mutation", "target_id": "t2"})
    assert len(log.records_for_target("t1")) == 1
    assert len(log.records_for_target("t2")) == 1
    assert len(log.records_for_target("t3")) == 0


def test_run_id_shape_and_uniqueness():
    ids = {new_run_id() for _ in range(200)}
    assert len(ids) == 200
    assert all("-" in i and len(i) >= 10 for i in ids)


def test_lines_are_valid_jsonl(tmp_path: Path):
    log = ProvenanceLog(tmp_path)
    log.append({"kind": "x", "a": 1})
    log.append({"kind": "y", "b": {"nested": [1, 2]}})
    for line in log.path.read_text().splitlines():
        json.loads(line)  # must not raise
