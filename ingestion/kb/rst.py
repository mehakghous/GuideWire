"""Minimal, deterministic reStructuredText reader for Blender manual source files. No model, no Sphinx.

It extracts only what GuideWire needs: the page title, sections with their heading path, clean prose, the structured
`.. reference::` block (Mode / Menu / Shortcut / Panel / Tool / Editor / Header), operator labels such as
`bpy.ops.mesh.bevel`, and "see also" links. Markup it does not understand is dropped, never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_ADORN = re.compile(r"^([=\-`:'\"~^_*+#<>.])\1{2,}\s*$")
_REF_START = re.compile(r"^\.\.\s+(?:reference::|admonition::\s*Reference)\s*$")
_FIELD = re.compile(r"^\s+:(\w+):\s*(.*)$")
_LABEL = re.compile(r"^\.\.\s+_([^:]+):\s*$")
_MENU = re.compile(r":menuselection:`([^`]+)`")
_KBD = re.compile(r":kbd:`([^`]+)`(?:\s*\(([^)]*)\))?")
_ROLE_TEXT = re.compile(r":(?:ref|doc|term|abbr|class|mod|func|bpy:\w+|guilabel|menuselection|kbd|sup|sub|math|mimetype|file|command|rna):`([^`]*)`")
_ROLE_ANY = re.compile(r":\w+(?::\w+)?:`")


def clean_inline(s: str) -> str:
    s = _MENU.sub(lambda m: m.group(1).replace("-->", ">").replace("--", ">"), s)
    s = re.sub(r":(?:ref|doc|abbr|term):`([^`<]*?)\s*<[^>]*>`", r"\1", s)            # :ref:`text <label>` -> text
    s = re.sub(r":doc:`/?([^`]*)`", lambda m: m.group(1).split("/")[-1].replace("_", " "), s)
    s = _ROLE_TEXT.sub(r"\1", s)
    s = re.sub(r"`([^`<]+?)\s*<[^>]*>`_{1,2}", r"\1", s)                                 # `text <url>`_
    s = re.sub(r"\|[^|\s][^|]*\|", "", s)                                                # |substitutions|
    s = s.replace("``", "").replace("**", "").replace("`", "")
    s = re.sub(r"(?<!\w)\*([^*\s][^*]*)\*(?!\w)", r"\1", s)
    return " ".join(s.split())


@dataclass
class Section:
    heading_path: list[str]
    text: str


@dataclass
class Reference:
    fields: dict[str, str]
    menus: list[str] = field(default_factory=list)                     # 'Edge > Bevel Edges'
    shortcuts: list[tuple[str, str | None]] = field(default_factory=list)   # ('Ctrl-B', 'Bevel Edges')
    modes: list[str] = field(default_factory=list)


@dataclass
class Page:
    path: str
    title: str
    sections: list[Section]
    reference: Reference | None                                        # the PAGE-LEVEL block (before any sub-heading)
    labels: list[str]
    operators: list[str]                                               # bpy.ops.mesh.bevel
    see_also: list[str]
    references: list = field(default_factory=list)                     # every block as (heading_path, Reference)


def parse_reference(lines: list[str]) -> Reference:
    fields: dict[str, str] = {}
    key = None
    for ln in lines:
        m = _FIELD.match(ln)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip()
        elif key and ln.strip():
            fields[key] += " " + ln.strip()
    menus = [m.group(1).replace("-->", ">").replace("--", ">") for m in _MENU.finditer(fields.get("Menu", ""))]
    menus = [" > ".join(p.strip() for p in x.split(">")) for x in menus]
    shortcuts = [(k.replace("Ctrl", "Ctrl"), lab.strip() if lab else None) for k, lab in _KBD.findall(fields.get("Shortcut", ""))]
    modes = [clean_inline(x) for x in re.split(r",|;", fields.get("Mode", "")) if clean_inline(x)]
    return Reference(fields, menus, shortcuts, modes)


def parse_page(path: str, text: str) -> Page:
    lines = text.splitlines()
    labels = [m.group(1) for ln in lines if (m := _LABEL.match(ln))]
    operators = [lb for lb in labels if lb.startswith("bpy.ops.")]
    title, sections, refs = "", [], []
    heading_stack: list[tuple[str, int]] = []
    levels: dict[str, int] = {}
    buf: list[str] = []
    cur_path: list[str] = []
    i = 0

    def flush():
        txt = "\n".join(buf).strip()
        if txt:
            sections.append(Section(list(cur_path), txt))
        buf.clear()

    while i < len(lines):
        ln = lines[i]
        if _REF_START.match(ln):
            j, blk = i + 1, []
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
                blk.append(lines[j])
                j += 1
            refs.append((list(cur_path), parse_reference(blk)))
            i = j
            continue
        # headings: [overline] text underline
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if ln.strip() and not ln.startswith((" ", "\t", "..")) and _ADORN.match(nxt) and len(nxt.strip()) >= max(3, len(ln.strip()) - 1) \
                and not _ADORN.match(ln):
            over = i > 0 and _ADORN.match(lines[i - 1]) is not None
            ch = nxt.strip()[0]
            key = ch * 2 if over else ch
            flush()
            lvl = levels.setdefault(key, len(levels))
            heading = clean_inline(ln)
            if not title and over:
                title = heading
            heading_stack = [(h, l) for h, l in heading_stack if l < lvl] + [(heading, lvl)]
            cur_path = [h for h, _ in heading_stack]
            i += 2
            continue
        if _ADORN.match(ln):          # overline of a heading or a transition
            i += 1
            continue
        if ln.startswith(".."):
            # directive or comment: drop the line and its indented body (figures, images, code, comments, labels)
            j = i + 1
            blk = []
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
                blk.append(lines[j])
                j += 1
            i = j
            continue
        buf.append(clean_inline(ln) if ln.strip() else "")
        i += 1
    flush()
    see = []
    for ln in lines:
        for m in re.finditer(r":doc:`/?([^`]+)`", ln):
            see.append(m.group(1))
    ref = next((r for hp, r in refs if len(hp) <= 1), None)   # a block under a sub-heading describes a sub-feature, not the page's tool
    return Page(path=path, title=title or path.split("/")[-1].replace("_", " ").title(), sections=sections, reference=ref,
                labels=labels, operators=operators, see_also=list(dict.fromkeys(see)), references=refs)


def lead_text(page: Page, max_chars: int = 420) -> str:
    """The page's first prose paragraph(s) (before the first sub-heading), trimmed at a sentence boundary."""
    parts = [s.text for s in page.sections if len(s.heading_path) <= 1]
    text = " ".join(" ".join(p.split()) for p in parts[:1]).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[: end + 1] if end > 120 else cut.rsplit(" ", 1)[0] + "...").strip()
