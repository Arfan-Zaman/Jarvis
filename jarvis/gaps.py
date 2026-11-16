"""The gap loop: what JARVIS could not do on its own becomes code that lets it do it next time.

1. Whenever JARVIS's own (local) way fails or Claude had to do the job instead, `record()` keeps a
   "gap": what was asked, what went wrong. The owner can add one by saying "learn to ..." or "teach
   yourself ...". Gaps are kept in settings (`gaps.open`), newest first, at most 40.
2. Every few hours while JARVIS is idle (`JARVIS_TEACH_HOURS`, default 6; or at once when the owner
   asks to learn something), the self-review hands the open gaps to Claude Code with one brief: build
   the ability INTO JARVIS (a tool, a route, a skill, a fix) with tests, so the local model can do it
   without Claude. That work happens in its own git worktree and branch, exactly like a self-review.
3. Nothing reaches `main` until the owner presses Approve on the System page (tests must pass on the
   merged result). The same protected paths apply: the safety rules and the reviewer itself never change.

So JARVIS calls Claude only for what it cannot do yet, and each call leaves it able to do more.
"""

from __future__ import annotations

import os
import re
import time

from .logging_setup import get_logger

log = get_logger("gaps")
OPEN_KEY = "gaps.open"
SENT_KEY = "gaps.sent"
LAST_KEY = "gaps.last_teach"
LIMIT = 40
TEACH_REQUEST = re.compile(r"^\W*(jarvis\W+)?(please\s+)?(learn|teach yourself|figure out)\s+(how\s+)?to\s+(.{6,})", re.I | re.S)


def teach_hours() -> float:
    try:
        return max(0.5, float(os.environ.get("JARVIS_TEACH_HOURS", "6")))
    except ValueError:
        return 6.0


def enabled() -> bool:
    return os.environ.get("JARVIS_TEACH", "1") != "0"


def record(app, kind: str, request: str, reason: str) -> dict | None:
    """Keep one gap. Same request twice is counted, not duplicated. Never raises."""
    try:
        request = " ".join(str(request).split())[:600]
        if not request:
            return None
        gaps = app.settings.get(OPEN_KEY) or []
        for gap in gaps:
            if gap["request"].lower() == request.lower():
                gap["count"] = gap.get("count", 1) + 1
                gap["reason"], gap["at"] = str(reason)[:400], time.strftime("%Y-%m-%dT%H:%M:%S")
                break
        else:
            gaps.insert(0, {"kind": kind, "request": request, "reason": str(reason)[:400], "count": 1,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        app.settings.set(OPEN_KEY, gaps[:LIMIT], category="learning", source="jarvis")
        app.events.record("system", "gap.recorded", f"JARVIS could not do on its own: {request[:120]}",
                          actor="jarvis:gaps", details={"kind": kind, "reason": str(reason)[:300]})
        return gaps[0]
    except Exception as exc:  # noqa: BLE001 - noting a gap must never break a reply
        log.info("Could not record a gap: %s", exc)
        return None


def open_gaps(app) -> list[dict]:
    return app.settings.get(OPEN_KEY) or []


def brief(gaps: list[dict]) -> str:
    lines = "\n".join(f"- [{g['kind']}] asked {g.get('count', 1)}x: {g['request']}\n  what went wrong: {g['reason']}"
                      for g in gaps)
    return (
        "TEACH JARVIS. The owner asked JARVIS for the things below and JARVIS could not do them on its own "
        "(its local model, its tools and its own Chrome were not enough, or Claude had to do the job). "
        "Pick up to 3 of them, most-asked and most useful first, and BUILD THE ABILITY INTO JARVIS so that "
        "next time its local model does it without Claude: a new or better tool under jarvis/tools (register "
        "it in jarvis/orchestrator.py), better routing or prompts in jarvis/engine/conversation.py, a fix for "
        "the failure, or a project skill. Standard library only; keep the approval rules (anything that sends, "
        "pays, deletes or runs commands still asks the owner). Add tests, keep the whole suite green, and in "
        "SELF_REVIEW.md say per gap what JARVIS can now do and how the owner should ask for it. If a gap needs "
        "something you may not add (a dependency, a download, a paid service, a permission), do not add it: "
        "write it under 'Needs the owner' in SELF_REVIEW.md with the exact command or step.\n\n"
        f"## Gaps\n{lines}\n")


def take(app, gaps: list[dict], branch: str | None) -> None:
    """Move gaps handed to Claude out of the open list (kept in `gaps.sent` with the branch)."""
    sent = app.settings.get(SENT_KEY) or []
    asked = {g["request"] for g in gaps}
    sent = [dict(g, branch=branch, sent=time.strftime("%Y-%m-%dT%H:%M:%S")) for g in gaps] + sent
    app.settings.set(SENT_KEY, sent[:LIMIT], category="learning", source="jarvis")
    app.settings.set(OPEN_KEY, [g for g in open_gaps(app) if g["request"] not in asked], category="learning", source="jarvis")
    app.settings.set(LAST_KEY, time.time(), category="learning", source="jarvis")


def due(app) -> bool:
    return enabled() and bool(open_gaps(app)) and time.time() - float(app.settings.get(LAST_KEY) or 0) >= teach_hours() * 3600
