import os
import time

from ingestion.retention import purge_derived


def test_old_derived_files_go_ledger_and_fresh_files_stay(tmp_path):
    for rel in ("runs/a.jsonl", "runs/cache/x.json", "runs/cache/new.json", "runs/ledger.json"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}")
    old = time.time() - 31 * 86400
    for rel in ("runs/a.jsonl", "runs/cache/x.json", "runs/ledger.json"):
        os.utime(tmp_path / rel, (old, old))
    assert sorted(purge_derived(tmp_path)) == ["runs/a.jsonl", "runs/cache/x.json"]
    assert (tmp_path / "runs/ledger.json").exists() and (tmp_path / "runs/cache/new.json").exists()
