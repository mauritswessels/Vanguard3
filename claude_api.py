"""One small helper for every call to Claude (the Messages API).

The News Analysts, the Opus Learner and the weekly report all use it, so a
refusal reads the same everywhere: with Anthropic's own reason, such as
"Your credit balance is too low", instead of just "HTTP Error 400". When
Claude is busy ("overloaded") it waits and tries once more.

``reply_text`` then reads the answer, and says plainly when Claude did not
finish it: the reply was cut off at its length limit, or Claude declined
to answer. Both come back as a normal reply, so without this check they
would only show up later as a vague "No JSON in the model's reply", or as
half a weekly report.

Calls that say who is asking (``purpose``) are also saved word for word in
``state/briefs/``, so every decision can be checked later
(``claude_archive.py``).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import claude_archive

URL = "https://api.anthropic.com/v1/messages"

#: Answers worth one more try after a pause: too many requests, server
#: trouble, overloaded.
BUSY = {429, 500, 502, 503, 504, 529}
RETRY_SECONDS = 30


def call_claude(body: dict, key: str, timeout: int = 120, tries: int = 2,
                purpose: str | None = None) -> dict:
    """Send ``body`` to the Messages API and return the parsed reply.

    With a ``purpose`` (who asks, such as "News Analyst") the request and
    the reply, or the error, are also saved in the archive
    (``claude_archive.py``). The key is not: it is not part of ``body``.
    """
    try:
        reply = _send(body, key, timeout, tries)
    except Exception as exc:
        if purpose:
            claude_archive.save(purpose, body, error=str(exc))
        raise
    if purpose:
        claude_archive.save(purpose, body, reply)
    return reply


def _send(body: dict, key: str, timeout: int, tries: int) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(
            URL, data=data, method="POST",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                why = json.loads(exc.read())["error"]["message"]
            except Exception:
                why = exc.reason
            if exc.code in BUSY and attempt < tries:
                time.sleep(RETRY_SECONDS)
                continue
            raise RuntimeError(f"Claude refused ({exc.code}): {why}") from None
    raise AssertionError("unreachable")


#: Why a reply can stop before Claude finished it, in plain words.
CUT_OFF = {
    "max_tokens": "it reached its length limit",
    "model_context_window_exceeded": "the question was too long for it",
}


def reply_text(reply: dict) -> str:
    """The text of a finished reply; an error saying why if it is not."""
    stop = reply.get("stop_reason")
    if stop == "refusal":
        # Its safety checks turned the question down (an HTTP 200 reply).
        # The category ("cyber", "bio", ...) may be missing.
        category = (reply.get("stop_details") or {}).get("category")
        raise RuntimeError(f"Claude declined: {category}" if category
                           else "Claude declined to answer")
    if stop in CUT_OFF:
        raise RuntimeError(f"Claude's reply was cut off ({CUT_OFF[stop]})")
    return "".join(b.get("text", "") for b in reply.get("content", [])
                   if b.get("type") == "text")
