"""The single entry point a UI (or the terminal `chat` command) talks to. No model, no network.

One `Service` owns: the knowledge index and tutorial index (if built), the conversation `Session`, and its save file. Everything goes through
`message(text)`, which returns a plain dict (JSON-serialisable) so any front end can use it:

    {"intent": "...", "route": "session|standalone|clarify|command", "kind": "...", "text": "<ready-to-show>", "bundle": {...AnswerBundle...} | None,
     "session": {...state...}}

A plain message goes to the follow-up resolver when a tutorial is loaded, otherwise to the router. Commands start with "/":
    /load last                    follow the steps of the last answer that had steps
    /load transcript FILE [SEC]   follow a transcript file (SRT/VTT/timed text); SEC = video length in seconds
    /load steps FILE              follow written instructions from a text file
    /state                        show the tutorial, step statuses and what is known about Blender
    /observe mode=EDIT_MESH selected_objects=MESH   record what Blender reports (or `clear`); stored, never used to complete a step
    /version 4.2                  set your Blender version
    /reset                        forget the tutorial and the conversation
Only an explicit user statement ("I did that", "skip this") changes step status; a question never does.
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from shared.answer import AnswerBundle

from . import session as S
from .followup import respond
from .router import route

LIST_KEYS = {"selected_objects", "selection_types", "open_panels"}


def _default_kb():
    from .kb.index import DEFAULT_DB, KnowledgeBase
    from .tutorials import load_index
    return (KnowledgeBase(DEFAULT_DB) if Path(DEFAULT_DB).exists() else None), load_index()


def render(b: AnswerBundle) -> str:
    """A compact, honest text rendering of an answer (what a terminal shows; a UI will render the bundle itself)."""
    out: list[str] = []
    if b.clarification:
        out.append(b.clarification)
    out += [q for q in b.questions if q != b.clarification]
    out += [e.text for e in b.explanations]
    if b.steps:
        for st in b.steps.steps:
            flag = f"  [{st.flags[0][:70]}]" if st.flags else ""
            out.append(f"  {st.order}. {st.goal}{flag}")
    for r in b.recommendations:
        bits = [x for x in [f"{r.duration_s / 60:.0f} min" if r.duration_s else None, f"Blender {r.blender_version_hint}" if r.blender_version_hint else None,
                            f"captions: {r.caption_kind}" if r.caption_kind else None] if x]
        out.append(f"  - {r.title} ({', '.join(bits) or 'no metadata'})\n    {r.url}")
    out += [f"Note: {c}" for c in b.caveats[:3]]
    if b.fallback_reason and not (b.steps or b.explanations or b.recommendations):
        out.append(b.fallback_reason)
    return "\n".join(x for x in out if x).strip() or "(no answer)"


@dataclass
class Service:
    session: S.Session
    session_path: Path | None = None
    kb: object | None = None
    tutorials: list | None = None
    last_bundle: AnswerBundle | None = None

    # ------------------------------------------------------------------ construction and persistence
    @classmethod
    def open(cls, session_path: str | Path | None = None, *, version: str | None = None, use_kb: bool = True) -> "Service":
        kb, tut = _default_kb() if use_kb else (None, None)
        path = Path(session_path) if session_path else None
        if path and path.exists():
            sess = S.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if version:
                sess.version = version
        else:
            sess = S.Session(version=version)
        return cls(sess, path, kb, tut)

    def save(self) -> None:
        if not self.session_path:
            return
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.session_path.with_suffix(self.session_path.suffix + ".tmp")
        tmp.write_text(json.dumps(S.to_dict(self.session), indent=1), encoding="utf-8")
        os.replace(tmp, self.session_path)                      # a crash never leaves a half-written session

    # ------------------------------------------------------------------ state
    def state(self) -> dict:
        s = self.session
        return {"loaded": s.steps is not None, "active": s.active, "tutorial": s.tutorial, "version": s.version, "current": s.current,
                "status": dict(s.status), "steps": [{"id": x.id, "goal": x.goal, "status": s.status.get(x.id)} for x in (s.steps.steps if s.steps else [])],
                "observed": s.observed, "has_pending_answer": bool(self.last_bundle and self.last_bundle.steps)}

    def _result(self, intent: str, route_: str, bundle: AnswerBundle | None, text: str | None = None) -> dict:
        self.save()
        return {"intent": intent, "route": route_, "kind": bundle.kind if bundle else "command", "text": text if text is not None else render(bundle),
                "bundle": bundle.model_dump(mode="json") if bundle else None, "session": self.state()}

    # ------------------------------------------------------------------ operations
    def message(self, text: str) -> dict:
        text = text.strip()
        if not text:
            return self._result("empty", "clarify", None, "Say something, or /help.")
        if text.startswith("/"):
            return self.command(text)
        reply = respond(self.session, text, kb=self.kb, tutorials=self.tutorials)
        if reply.bundle.steps and reply.route != "session":
            self.last_bundle = reply.bundle
        out = self._result(reply.intent, reply.route, reply.bundle)
        if reply.bundle.steps and reply.route != "session":
            out["text"] += "\n(say /load last to follow these steps and ask questions about them)"
        return out

    def load(self, bundle: AnswerBundle, tutorial: dict | None = None) -> dict:
        self.session.load(bundle, tutorial=tutorial, version=self.session.version)
        self.session.observed = self.session.observed        # kept: observed state belongs to the user's Blender, not the tutorial
        first = self.session.current_step
        return self._result("load", "command", None, f"Loaded {len(self.session.steps.steps)} steps from {(self.session.tutorial or {}).get('title') or 'the procedure'}. "
                                                       f"You are on {first.id}: {first.goal}. Nothing is marked done.")

    def command(self, line: str) -> dict:
        try:
            parts = [x[1:-1] if len(x) > 1 and x[0] == x[-1] and x[0] in "\"'" else x for x in shlex.split(line, posix=False)]   # quotes keep paths with spaces whole
        except ValueError as e:
            return self._result("error", "command", None, f"error: {e}")
        cmd, args = parts[0].lower(), parts[1:]
        try:
            if cmd == "/help":
                return self._result("help", "command", None, (__doc__ or "").split("Commands start with")[1].split("Only an explicit")[0].strip(": \n"))
            if cmd == "/state":
                st = self.state()
                lines = [f"tutorial: {(st['tutorial'] or {}).get('title') or 'none loaded'}; Blender version: {st['version'] or 'unknown'}; active: {st['active']}"]
                lines += [f"  {'>' if x['id'] == st['current'] else ' '} {x['id']} [{x['status']}] {x['goal']}" for x in st["steps"]]
                lines.append(f"Blender state: {st['observed'] or 'not observed'}")
                return self._result("state", "command", None, "\n".join(lines))
            if cmd == "/reset":
                self.session, self.last_bundle = S.Session(version=self.session.version), None
                return self._result("reset", "command", None, "Forgot the tutorial and the conversation.")
            if cmd == "/version" and args:
                self.session.version = args[0]
                return self._result("version", "command", None, f"Blender version set to {args[0]}.")
            if cmd == "/observe":
                if args == ["clear"]:
                    self.session.observed = None
                    return self._result("observe", "command", None, "Cleared what Blender reported.")
                obs = {}
                for a in args:
                    k, _, v = a.partition("=")
                    if not v:
                        raise ValueError(f"expected key=value, got {a!r}")
                    obs[k] = [x for x in v.split(",") if x] if k in LIST_KEYS else v
                self.session.observed = {**(self.session.observed or {}), **obs}
                return self._result("observe", "command", None, f"Recorded: {self.session.observed}. This does not mark any step done.")
            if cmd == "/load" and args:
                kind = args[0]
                if kind == "last":
                    if not (self.last_bundle and self.last_bundle.steps):
                        raise ValueError("there is no earlier answer with steps to follow; ask for a procedure first")
                    return self.load(self.last_bundle)
                if kind in ("transcript", "steps") and len(args) >= 2:
                    text = Path(args[1]).read_text(encoding="utf-8")
                    if kind == "transcript":
                        dur = float(args[2]) if len(args) > 2 else None
                        b = route(text, version=self.session.version, input_type="transcript", duration_s=dur)
                        tut = {"title": Path(args[1]).name, "source_type": "transcript", "version_hint": None}
                    else:
                        b = route(text, version=self.session.version)
                        tut = {"title": Path(args[1]).name, "source_type": "written", "version_hint": None}
                    if not b.steps:
                        raise ValueError("no steps could be built from that file: " + (b.fallback_reason or b.clarification or "nothing recognised"))
                    return self.load(b, tut)
            return self._result("unknown", "command", None, f"Unknown or incomplete command: {line}. Try /help.")
        except (OSError, ValueError) as e:
            return self._result("error", "command", None, f"error: {str(e).splitlines()[0][:200]}")


def chat(service: Service, lines, out=print, as_json: bool = False, prompt: str | None = None) -> int:
    """Run a conversation over an iterable of input lines. `/quit` or the end of input stops it."""
    for line in lines:
        line = line.rstrip("\n")
        if line.strip().lower() in ("/quit", "/exit"):
            break
        r = service.message(line)
        out(json.dumps(r, indent=1) if as_json else r["text"])
    return 0
