"""Build the local knowledge index from the fetched manual sources and the title inventory.

    python -m ingestion.kb.build          # reads knowledge/cache/<branch>/ and knowledge/cache/site_titles_main.json, writes knowledge/kb.sqlite

Run `python -m ingestion.kb.fetch --branch main --inventory` first. The index is a local build artifact (git-ignored).
"""
from __future__ import annotations

import json

from .index import CACHE, DEFAULT_DB, KnowledgeBase


def main() -> int:
    sources = {d.name: d for d in sorted(CACHE.iterdir()) if d.is_dir()} if CACHE.exists() else {}
    if "main" not in sources:
        print("no fetched pages found: run  python -m ingestion.kb.fetch --branch main --inventory  first")
        return 2
    titles_file = CACHE / "site_titles_main.json"
    titles = json.loads(titles_file.read_text(encoding="utf-8")) if titles_file.exists() else {}
    kb = KnowledgeBase.build(sources, DEFAULT_DB, titles)
    print(json.dumps(kb.stats(), indent=1), "| site titles:", len(titles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
