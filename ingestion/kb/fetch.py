"""Targeted, polite, resumable retrieval of a CURATED subset of the Blender manual's source files.

Why this and not a crawl: the manual is CC-BY-SA 4.0 and its source files are published in a public git repository. We read
only the subtrees GuideWire needs (see CORE_SCOPE), one file per request at a low rate, with an identifying User-Agent, and stop at
the first 403/429. The file list comes from the repository host's documented tree API (paths and sizes, no content). Nothing is
scraped from rendered HTML, no search page is touched, and no access control is bypassed.

The fetched text stays in knowledge/cache/ (git-ignored). What IS committed is knowledge/KB_MANIFEST.json: page paths, sha256,
branch and retrieval date, so the index can be rebuilt and audited without storing CC-BY-SA text in this repository.

    python -m ingestion.kb.fetch --branch main            # ~284 files, about 1 MB, ~2 minutes
    python -m ingestion.kb.fetch --branch blender-v2.93-release --only modeling/meshes/editing/edge/bevel scene_layout/object/editing/join
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "knowledge" / "cache"
MANIFEST = ROOT / "knowledge" / "KB_MANIFEST.json"
API = "https://projects.blender.org/api/v1/repos/blender/blender-manual"
RAW = "https://projects.blender.org/blender/blender-manual/raw/branch"
UA = "GuideWire-FYP/0.1 (university final-year project; targeted manual-source lookups; low rate)"
LICENCE = "CC-BY-SA 4.0; credit: Blender Documentation Team (https://docs.blender.org/manual/en/latest/copyright.html)"

# The mesh-modelling, object, 3D-viewport and interface subtrees: ~284 pages, ~0.85 MB. Everything else in the manual (modifiers,
# sculpting, rendering, animation, ...) is deliberately OUT of the local index; questions about it are reported as outside_index.
CORE_SCOPE = ("modeling/meshes", "scene_layout/object", "editors/3dview", "interface/undo_redo", "interface/selecting", "interface/controls")


class FetchStop(RuntimeError):
    pass


def list_pages(client: httpx.Client, branch: str, delay: float = 0.6) -> list[dict]:
    ents: list[dict] = []
    for page in range(1, 12):
        r = client.get(f"{API}/git/trees/{branch}", params={"recursive": "true", "per_page": "1000", "page": str(page)})
        if r.status_code in (403, 429):
            raise FetchStop(f"tree API refused with HTTP {r.status_code}")
        r.raise_for_status()
        d = r.json()
        ents += d.get("tree", [])
        if not d.get("truncated"):
            break
        time.sleep(delay)
    return [{"path": e["path"][len("manual/"):-4], "size": e.get("size", 0)}
            for e in ents if e["path"].startswith("manual/") and e["path"].endswith(".rst")]


def in_scope(page: str, scope=CORE_SCOPE) -> bool:
    return any(page == s or page.startswith(s + "/") or page.startswith(s) for s in scope)


def fetch_branch(branch: str, only: list[str] | None = None, delay: float = 0.4, client: httpx.Client | None = None) -> dict:
    client = client or httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
    pages = list_pages(client, branch) if not only else [{"path": p, "size": 0} for p in only]
    pages = [p for p in pages if (only or in_scope(p["path"]))]
    out_dir = CACHE / branch
    got = skipped = 0
    entries = []
    for p in pages:
        dest = out_dir / (p["path"] + ".rst")
        if dest.exists():
            skipped += 1
            data = dest.read_bytes()
        else:
            r = client.get(f"{RAW}/{branch}/manual/{p['path']}.rst")
            if r.status_code in (403, 429):
                raise FetchStop(f"refused with HTTP {r.status_code} at {p['path']}; stopping (nothing else was requested)")
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.content
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            got += 1
            time.sleep(delay)
        entries.append({"path": p["path"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {"branch": branch, "retrieved": date.today().isoformat(), "licence": LICENCE, "pages": entries, "fetched": got, "reused": skipped}


def fetch_inventory(branch_url: str = "https://docs.blender.org/manual/en/latest", client: httpx.Client | None = None) -> dict:
    """The manual site's own Sphinx inventory (objects.inv): page paths and titles for the WHOLE manual, no page content. It is the
    file Sphinx publishes for cross-referencing; one request. Used only to point at the right official page for questions the local
    index does not cover. Returns {doc_path: title}."""
    import re
    import zlib

    client = client or httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
    r = client.get(f"{branch_url}/objects.inv")
    if r.status_code in (403, 429):
        raise FetchStop(f"objects.inv refused with HTTP {r.status_code}")
    r.raise_for_status()
    data = r.content
    pos = 0
    for _ in range(4):                      # four plain-text header lines, then zlib data
        pos = data.index(b"\n", pos) + 1
    out: dict[str, str] = {}
    for line in zlib.decompress(data[pos:]).decode("utf-8").splitlines():
        m = re.match(r"^(\S+)\s+std:doc\s+(-?\d+)\s+(\S+)\s+(.*)$", line)
        if m:
            name, _, uri, disp = m.groups()
            out[name.lstrip("/")] = name.split("/")[-1].replace("_", " ").title() if disp.strip() == "-" else disp.strip()
    return out


def write_manifest(result: dict) -> None:
    m = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"branches": {}}
    m["branches"][result["branch"]] = {k: result[k] for k in ("retrieved", "licence", "pages")}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--inventory", action="store_true", help="also fetch objects.inv (page titles of the whole manual)")
    a = ap.parse_args(argv)
    try:
        if a.inventory:
            inv = fetch_inventory()
            (CACHE / "site_titles_main.json").parent.mkdir(parents=True, exist_ok=True)
            (CACHE / "site_titles_main.json").write_text(json.dumps(inv, indent=0), encoding="utf-8")
            print(f"inventory: {len(inv)} page titles")
        res = fetch_branch(a.branch, a.only)
    except FetchStop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 3
    write_manifest(res)
    print(f"{res['branch']}: fetched {res['fetched']}, reused {res['reused']}, {len(res['pages'])} pages, "
          f"{sum(p['bytes'] for p in res['pages']) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
