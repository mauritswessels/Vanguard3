"""Archive of every Claude call: what Claude read and what it answered.

Each call to Claude is saved word for word, so that every decision can be
checked, and graded again later, long after the dashboard has moved on:
the News Analysts' evening and midday decisions, the Opus Learner's review
and the weekly report. A call keeps the exact request (model, settings,
system prompt and the message, which holds the full news brief) and the
reply (its text, the model that answered, the tokens used and why it
stopped), or the error when there was no reply.

The API key is never saved: it travels in a request header, and only the
request body and the reply are kept.

One compressed file per day (UTC) in ``state/briefs/``, for example
``state/briefs/2026-10-21.json.xz``: a JSON list of the day's calls in the
order they happened. xz keeps a day's calls small because they repeat each
other: both News Analysts read the same brief. To read one::

    python claude_archive.py                     # the newest day, in short
    python claude_archive.py 2026-10-21          # that day, in short
    python claude_archive.py 2026-10-21 --full   # with every text in full

Saving is best effort: if it fails, the reply is used all the same and the
log says why. Trading never waits for the archive.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import lzma
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger("vanguard3.archive")

FOLDER = config.PROJECT_ROOT / "state" / "briefs"
SUFFIX = ".json.xz"


def day_file(day: str) -> Path:
    return FOLDER / f"{day}{SUFFIX}"


def load(day: str) -> list[dict]:
    """The calls saved on ``day`` (YYYY-MM-DD), oldest first."""
    path = day_file(day)
    if not path.exists():
        return []
    with lzma.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def record(purpose: str, body: dict, reply: dict | None, error: str | None,
           when: datetime) -> dict:
    """One call as it is saved: the request body as sent, the reply text."""
    entry = {"time_utc": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "purpose": purpose, "request": body}
    if reply is not None:
        entry["reply"] = {
            "model": reply.get("model"), "id": reply.get("id"),
            "stop_reason": reply.get("stop_reason"),
            "stop_details": reply.get("stop_details"),
            "usage": reply.get("usage", {}),
            # Thinking blocks are left out: their text is empty unless asked
            # for, and their signature means nothing outside the API.
            "text": "".join(b.get("text", "") for b in reply.get("content", [])
                            if b.get("type") == "text")}
    if error is not None:
        entry["error"] = error
    return entry


def save(purpose: str, body: dict, reply: dict | None = None,
         error: str | None = None, when: datetime | None = None) -> bool:
    """Add one call to its day's file. Never raises: False if it failed."""
    tmp = None
    try:
        when = when or datetime.now(timezone.utc)
        day = when.strftime("%Y-%m-%d")
        # A file that cannot be read stays as it is (load raises): this one
        # call is then not saved, but the day's earlier calls are not lost.
        calls = load(day) + [record(purpose, body, reply, error, when)]
        FOLDER.mkdir(parents=True, exist_ok=True)
        path = day_file(day)
        tmp = path.with_suffix(".tmp")
        with lzma.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(calls, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(path)            # all or nothing, never half a file
        return True
    except Exception as exc:
        logger.warning("Could not archive the %s call to Claude: %s",
                       purpose, exc)
        if tmp is not None:          # the bots commit everything in state/
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return False


def show(calls: list[dict], full: bool = False) -> str:
    """The calls as plain text: in short, or with every text in full."""
    out = []
    for i, c in enumerate(calls, 1):
        req, rep = c["request"], c.get("reply") or {}
        usage = rep.get("usage") or {}
        out.append(f"#{i} {c['time_utc']}  {c['purpose']}  "
                   f"{rep.get('model') or req.get('model')}  "
                   f"stop: {rep.get('stop_reason', '-')}  tokens in/out: "
                   f"{usage.get('input_tokens', '-')}/"
                   f"{usage.get('output_tokens', '-')}")
        if c.get("error"):
            out.append(f"   error: {c['error']}")
        text = rep.get("text", "")
        if not full:
            if text:
                out.append("   reply: " + " ".join(text.split())[:200])
            continue
        system = req.get("system", "")
        out += ["", "--- system ---", system if isinstance(system, str)
                else json.dumps(system, indent=1)]
        for m in req.get("messages", []):
            content = m.get("content")
            out += [f"--- {m.get('role')} ---", content if isinstance(
                content, str) else json.dumps(content, indent=1)]
        out += ["--- reply ---", text, ""]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("day", nargs="?",
                        help="YYYY-MM-DD (default: the newest day saved)")
    parser.add_argument("--full", action="store_true",
                        help="print the full request and reply texts")
    args = parser.parse_args()
    days = sorted(p.name[:10] for p in FOLDER.glob(f"*{SUFFIX}"))
    day = args.day or (days[-1] if days else None)
    if not day or day not in days:
        raise SystemExit(f"No archive for {day or 'any day'} in {FOLDER}")
    print(show(load(day), args.full))


if __name__ == "__main__":
    main()
