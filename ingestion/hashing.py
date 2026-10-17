"""Freeze checks that do not depend on the operating system's line endings.

Frozen files were hashed on Windows, some with CRLF bytes; git stores text with LF and a Linux checkout has LF. The CONTENT is what is frozen,
so a file matches when its bytes hash to the recorded value under LF or under CRLF line endings. A change of even one character still fails.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def candidate_hashes(data: bytes) -> set[str]:
    lf = data.replace(b"\r\n", b"\n")
    return {hashlib.sha256(x).hexdigest() for x in (data, lf, lf.replace(b"\n", b"\r\n"))}


def matches_frozen(path: str | Path, recorded_hash_file: str | Path) -> tuple[bool, str]:
    """(ok, sha256 of the bytes as stored). `recorded_hash_file` holds the hash as its first whitespace-separated token."""
    data = Path(path).read_bytes()
    want = Path(recorded_hash_file).read_text(encoding="utf-8").split()
    want = next((w for w in want if len(w) == 64), "")
    return want in candidate_hashes(data), hashlib.sha256(data).hexdigest()
