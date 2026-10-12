"""Local full-text index over the fetched manual source: SQLite FTS5 (standard library, no new dependency), BM25 ranking.

Chosen after comparing options (see the plan, section 'Architecture options'): the indexed scope is ~0.85 MB of text, so a
plain FTS index answers in milliseconds with no network and no model; embeddings or a vector store would add dependencies and
hosting for no measured gain at this size. The index is a BUILD ARTIFACT (git-ignored) so CC-BY-SA text is not committed.

Query handling is deterministic: stopword removal, Porter stemming inside FTS5, BM25 with title/heading/body weights, and a
separate title-match check. `sufficient` is an explicit decision (not a score threshold hidden in the caller) so the router can
decline instead of answering from an unrelated page.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .rst import Page, lead_text, parse_page

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "knowledge" / "kb.sqlite"
CACHE = ROOT / "knowledge" / "cache"
BRANCH_URL = {"main": "latest"}

STOPWORDS = frozenset("""a an the to of in on at is are was were be been do does did how what why when where which who whom can could
would should will i me my we you your it its this that these those with for and or but not no as by from about into between
difference different between versus vs please blender tell show explain use using get make want need find give
doesn isn won don didn couldn wasn aren""".split())
# 'make', 'show', 'explain', 'find', 'give' are request verbs, not topics; 'add', 'select', 'delete', 'merge' ARE topics and stay.


def terms(query: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", query.lower())
    return [t for t in toks if t not in STOPWORDS and len(t) > 1]


def stem(w: str) -> str:
    """Crude shared stemmer: bake/baking/baked -> bak, edges -> edg, objects -> object. Used only to compare words."""
    for suf in ("ing", "ed", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def page_url(path: str, branch: str = "main") -> str:
    return f"https://docs.blender.org/manual/en/{BRANCH_URL.get(branch, branch.replace('blender-v', '').replace('-release', ''))}/{path}.html"


@dataclass
class Hit:
    path: str
    branch: str
    title: str
    score: float                     # BM25 (lower = better), best chunk of the page
    title_terms: int                 # how many query terms occur in the page title / path words
    n_terms: int
    url: str
    lead: str
    reference: dict | None
    operators: list[str] = field(default_factory=list)
    best_heading: str = ""


@dataclass
class SearchResult:
    query: str
    terms: list[str]
    hits: list[Hit]
    sufficient: bool
    reason: str
    outside_index: bool = False                       # the manual has a better-matching page that is not in the local index
    elsewhere: list = field(default_factory=list)     # [(path, title)] official pages to point at (titles only, no content)


class KnowledgeBase:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.path = Path(db_path)
        self.con = sqlite3.connect(str(self.path))
        self.con.row_factory = sqlite3.Row

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, sources: dict[str, Path], db_path: str | Path = DEFAULT_DB, site_titles: dict[str, str] | None = None) -> "KnowledgeBase":
        """sources: {branch: directory containing <page path>.rst files}."""
        db_path = Path(db_path)
        if db_path.exists():
            db_path.unlink()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(db_path))
        con.executescript("""
            CREATE TABLE pages(path TEXT, branch TEXT, title TEXT, lead TEXT, reference TEXT, operators TEXT, see_also TEXT, nbytes INT,
                               PRIMARY KEY(path, branch));
            CREATE VIRTUAL TABLE chunks USING fts5(title, heading, body, path UNINDEXED, branch UNINDEXED, tokenize='porter unicode61');
            CREATE VIRTUAL TABLE page_titles USING fts5(title, path UNINDEXED, branch UNINDEXED, tokenize='porter unicode61');
            CREATE TABLE site_titles(path TEXT PRIMARY KEY, title TEXT);
        """)
        for branch, root in sources.items():
            for f in sorted(Path(root).rglob("*.rst")):
                rel = f.relative_to(root).as_posix()[:-4]
                text = f.read_text(encoding="utf-8")
                pg: Page = parse_page(rel, text)
                words = " ".join(rel.split("/")[-3:]).replace("_", " ").replace("-", " ")   # location words: object/editing/clear
                ref = None
                if pg.reference:
                    ref = json.dumps({"fields": pg.reference.fields, "menus": pg.reference.menus, "shortcuts": pg.reference.shortcuts,
                                      "modes": pg.reference.modes})
                con.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)", (rel, branch, pg.title, lead_text(pg), ref, json.dumps(pg.operators),
                                                                         json.dumps(pg.see_also), len(text.encode())))
                con.execute("INSERT INTO page_titles VALUES (?,?,?)", (f"{pg.title} {words}", rel, branch))
                if not pg.sections:
                    con.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (f"{pg.title} {words}", "", "", rel, branch))
                for s in pg.sections:
                    con.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (f"{pg.title} {words}", " > ".join(s.heading_path), s.text, rel, branch))
        for p, t in (site_titles or {}).items():
            con.execute("INSERT OR REPLACE INTO site_titles VALUES (?,?)", (p, t))
        con.commit()
        con.close()
        return cls(db_path)

    # ------------------------------------------------------------------ search
    def stats(self) -> dict:
        r = self.con.execute("SELECT COUNT(*) n, SUM(nbytes) b FROM pages").fetchone()
        return {"pages": r["n"], "source_bytes": r["b"], "db_bytes": self.path.stat().st_size,
                "branches": [x[0] for x in self.con.execute("SELECT DISTINCT branch FROM pages")]}

    def get_page(self, path: str, branch: str = "main") -> Hit | None:
        r = self.con.execute("SELECT * FROM pages WHERE path=? AND branch=?", (path, branch)).fetchone()
        return self._hit(r, 0.0, 0, 0, "") if r else None

    def _hit(self, r, score, tt, nt, heading) -> Hit:
        return Hit(path=r["path"], branch=r["branch"], title=r["title"], score=score, title_terms=tt, n_terms=nt,
                   url=page_url(r["path"], r["branch"]), lead=r["lead"], reference=json.loads(r["reference"]) if r["reference"] else None,
                   operators=json.loads(r["operators"] or "[]"), best_heading=heading)

    def search(self, query: str, branch: str = "main", limit: int = 5) -> SearchResult:
        ts = terms(query)
        if not ts:
            return SearchResult(query, ts, [], False, "no content words in the query")
        match = " OR ".join(f'"{t}"' for t in ts)
        rows = self.con.execute(
            "SELECT path, heading, bm25(chunks, 8.0, 4.0, 1.0) AS s FROM chunks WHERE chunks MATCH ? AND branch=? ORDER BY s LIMIT 60",
            (match, branch)).fetchall()
        best: dict[str, tuple[float, str]] = {}
        for r in rows:
            if r["path"] not in best or r["s"] < best[r["path"]][0]:
                best[r["path"]] = (r["s"], r["heading"])
        # which query terms occur in each candidate page's TITLE (stemmed by FTS5)
        title_hits: dict[str, set[str]] = {}
        for t in ts:
            for r in self.con.execute("SELECT path FROM page_titles WHERE page_titles MATCH ? AND branch=?", (f'"{t}"', branch)):
                title_hits.setdefault(r["path"], set()).add(t)
        titles = {r["path"]: r["title"] for r in self.con.execute(
            f"SELECT path, title FROM pages WHERE branch=? AND path IN ({','.join('?' * len(best))})", (branch, *best))} if best else {}

        def key(kv):
            th = len(title_hits.get(kv[0], ()))
            extra = max(0, len(re.findall(r"\w+", titles.get(kv[0], ""))) - th)     # title words the query did not ask for: prefer the exact page
            return (kv[1][0] - 3.0 * th + 0.3 * extra, kv[0])
        ranked = sorted(best.items(), key=key)[:limit]
        hits = []
        for path, (s, heading) in ranked:
            r = self.con.execute("SELECT * FROM pages WHERE path=? AND branch=?", (path, branch)).fetchone()
            hits.append(self._hit(r, s, len(title_hits.get(path, ())), len(ts), heading))
        sufficient, reason = self._decide(hits, ts)
        outside, elsewhere = False, []
        if self._has_site_titles():
            # the best local candidate by title+path words (not merely the top-ranked one): a same-named page elsewhere (UV snapping vs 3D
            # Viewport snapping) is not a reason to call the topic 'outside'
            top_n = max((self._count_terms(ts, h.title + " " + h.path.replace("/", " ").replace("_", " ")) for h in hits), default=0)
            sites = self.site_title_search(query, limit=3, with_counts=True)
            if sites and sites[0][2] > top_n and sites[0][0] not in {h.path for h in hits}:
                outside, elsewhere = True, [(p, t) for p, t, _ in sites]
                sufficient, reason = False, f"the manual has a better-matching page that is not in the local index: '{sites[0][1]}'"
        return SearchResult(query, ts, hits, sufficient, reason, outside, elsewhere)

    def _has_site_titles(self) -> bool:
        return self.con.execute("SELECT COUNT(*) FROM site_titles").fetchone()[0] > 0

    @staticmethod
    def _count_terms(ts: list[str], blob: str) -> int:
        have = {stem(w) for w in re.findall(r"[a-z0-9]+", blob.lower())}
        return sum(1 for t in ts if stem(t) in have)

    @staticmethod
    def _decide(hits: list[Hit], ts: list[str]) -> tuple[bool, str]:
        """Answer from the index only when the best page is plausibly ABOUT the question: at least one query term in its title or location
        words, and at least half of the query's content terms covered (or two terms). Otherwise decline rather than answer from a loose match."""
        if not hits:
            return False, "no page matches any content word"
        top = hits[0]
        if top.title_terms == 0:
            return False, f"no query term appears in the title of the best page ('{top.title}')"
        if top.title_terms * 2 < len(ts) and top.title_terms < 2:
            return False, f"only {top.title_terms} of {len(ts)} query terms appear in the title of the best page ('{top.title}')"
        return True, f"title of '{top.title}' contains {top.title_terms} of {len(ts)} query terms"

    def pages_with_shortcut(self, shortcut: str, branch: str = "main") -> list[dict]:
        """Pages whose Reference block lists this normalised shortcut (used to detect collisions)."""
        from .candidates import normalise_kbd

        if not hasattr(self, "_sc_map"):
            self._sc_map: dict[str, list[dict]] = {}
            for r in self.con.execute("SELECT path, branch, title, reference FROM pages WHERE reference IS NOT NULL"):
                ref = json.loads(r["reference"])
                for k, _ in ref.get("shortcuts", []):
                    n = normalise_kbd(k)[0]
                    if n:
                        self._sc_map.setdefault(f"{r['branch']}|{n}", []).append({"path": r["path"], "title": r["title"], "modes": ref.get("modes", [])})
        return self._sc_map.get(f"{branch}|{shortcut}", [])

    def menu_names(self, branch: str = "main") -> list[str]:
        """Every menu path the manual's Reference blocks state (authoritative UI labels), for extending the UI-name vocabulary."""
        out: set[str] = set()
        for r in self.con.execute("SELECT reference FROM pages WHERE reference IS NOT NULL AND branch=?", (branch,)):
            out.update(json.loads(r["reference"]).get("menus", []))
        return sorted(out)

    def site_title_search(self, query: str, limit: int = 3, with_counts: bool = False):
        """Whole-manual page TITLES (no content) matching the query: used only to point at the right official page."""
        ts = terms(query)
        scored = []
        for r in self.con.execute("SELECT path, title FROM site_titles"):
            n = self._count_terms(ts, r["title"] + " " + r["path"].replace("/", " ").replace("_", " "))
            if n:
                scored.append((n * 2 + sum(1 for t in ts if t in r["title"].lower()), n, r["path"], r["title"]))
        scored.sort(key=lambda x: (-x[0], len(x[2])))
        return [(p, t, n) if with_counts else (p, t) for _, n, p, t in scored[:limit]]
