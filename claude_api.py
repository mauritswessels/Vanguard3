"""One small helper for every call to Claude (the Messages API).

The News Analysts, the Opus Learner and the weekly report all use it, so a
refusal reads the same everywhere: with Anthropic's own reason, such as
"Your credit balance is too low", instead of just "HTTP Error 400". When
Claude is busy ("overloaded") it waits and tries once more.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

URL = "https://api.anthropic.com/v1/messages"

#: Answers worth one more try after a pause: too many requests, server
#: trouble, overloaded.
BUSY = {429, 500, 502, 503, 504, 529}
RETRY_SECONDS = 30


def call_claude(body: dict, key: str, timeout: int = 120,
                tries: int = 2) -> dict:
    """Send ``body`` to the Messages API and return the parsed reply."""
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
