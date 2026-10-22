"""The archive of Claude calls: word for word, no key, never in the way."""

import io
import json
import lzma
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import claude_api
import claude_archive

KEY = "sk-ant-test-secret-key"


def reply(text, stop="end_turn"):
    return {"id": "msg_1", "model": "claude-sonnet-5-5", "stop_reason": stop,
            "stop_details": None, "usage": {"input_tokens": 40000,
                                            "output_tokens": 600},
            "content": [{"type": "thinking", "thinking": "",
                         "signature": "opaque"},
                        {"type": "text", "text": text}]}


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.folder = tmp / "state" / "briefs"
        self.enterContext(mock.patch.object(claude_archive, "FOLDER",
                                            self.folder))

    def call(self, *answers, purpose="News Analyst"):
        """call_claude with the network replaced by ``answers``."""
        sent = []

        def urlopen(req, timeout):
            sent.append(req)
            a = answers[len(sent) - 1]
            if isinstance(a, int):
                raise urllib.error.HTTPError(
                    req.full_url, a, "Bad", {}, io.BytesIO(json.dumps(
                        {"error": {"message": "Your credit balance is too "
                                              "low"}}).encode()))
            return io.BytesIO(json.dumps(a).encode())

        body = {"model": "claude-sonnet-5-5", "max_tokens": 8000,
                "system": "You manage one account.",
                "messages": [{"role": "user", "content": "SPY: news brief"}]}
        with mock.patch.object(claude_api.urllib.request, "urlopen", urlopen):
            return claude_api.call_claude(body, KEY, purpose=purpose)

    def test_saves_the_request_and_the_reply_word_for_word(self):
        self.call(reply('{"targets": {}}'))
        (path,) = self.folder.iterdir()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(path.name, f"{today}.json.xz")
        (call,) = claude_archive.load(today)
        self.assertEqual(call["purpose"], "News Analyst")
        self.assertEqual(call["request"]["system"], "You manage one account.")
        self.assertEqual(call["request"]["messages"][0]["content"],
                         "SPY: news brief")
        self.assertEqual(call["request"]["max_tokens"], 8000)
        self.assertEqual(call["reply"]["text"], '{"targets": {}}')
        self.assertEqual(call["reply"]["stop_reason"], "end_turn")
        self.assertEqual(call["reply"]["usage"]["output_tokens"], 600)
        self.assertNotIn("signature", json.dumps(call))

    def test_never_saves_the_key(self):
        self.call(reply("{}"))
        with self.assertRaises(RuntimeError):
            self.call(400)              # failed calls are saved too
        raw = b"".join(lzma.open(p).read() for p in self.folder.iterdir())
        self.assertNotIn(KEY.encode(), raw)
        self.assertNotIn(b"x-api-key", raw)

    def test_calls_of_a_day_are_added_in_order(self):
        self.call(reply("evening"), purpose="News Analyst")
        self.call(reply("review"), purpose="Opus Learner")
        self.call(reply("cut", stop="max_tokens"), purpose="News Analyst")
        with self.assertRaises(RuntimeError):
            self.call(400)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        calls = claude_archive.load(today)
        self.assertEqual([c["purpose"] for c in calls],
                         ["News Analyst", "Opus Learner", "News Analyst",
                          "News Analyst"])
        self.assertEqual(calls[2]["reply"]["stop_reason"], "max_tokens")
        self.assertNotIn("reply", calls[3])
        self.assertIn("credit balance is too low", calls[3]["error"])
        # Without a purpose nothing is saved (the tests of the call itself).
        self.call(reply("x"), purpose=None)
        self.assertEqual(len(claude_archive.load(today)), 4)

    def test_one_file_per_day(self):
        body = {"model": "m", "messages": []}
        for day in ("2026-10-20", "2026-10-21", "2026-10-21"):
            when = datetime.fromisoformat(day + "T20:30:00+00:00")
            self.assertTrue(claude_archive.save("News Analyst", body,
                                                reply("ok"), when=when))
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["2026-10-20.json.xz", "2026-10-21.json.xz"])
        self.assertEqual(len(claude_archive.load("2026-10-21")), 2)
        self.assertEqual(claude_archive.load("2026-10-21")[0]["time_utc"],
                         "2026-10-21T20:30:00Z")

    def test_a_failing_archive_never_stops_the_call(self):
        # A file where the folder should be: nothing can be written.
        self.folder.parent.mkdir(parents=True)
        self.folder.write_text("not a folder")
        with self.assertLogs("vanguard3.archive", "WARNING"):
            out = self.call(reply('{"targets": {}}'))
        self.assertEqual(out["content"][1]["text"], '{"targets": {}}')

    def test_a_broken_file_is_left_alone(self):
        self.folder.mkdir(parents=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        broken = self.folder / f"{today}.json.xz"
        broken.write_bytes(b"not xz")
        with self.assertLogs("vanguard3.archive", "WARNING"):
            self.call(reply("{}"))
        self.assertEqual(broken.read_bytes(), b"not xz")
        self.assertEqual([p.name for p in self.folder.iterdir()],
                         [broken.name])     # no temporary file left behind

    def test_shows_a_day_in_short_and_in_full(self):
        self.call(reply('{"market_view": "calm"}'))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        short = claude_archive.show(claude_archive.load(today))
        self.assertIn("News Analyst", short)
        self.assertIn("stop: end_turn", short)
        self.assertIn("40000/600", short)
        self.assertNotIn("SPY: news brief", short)
        full = claude_archive.show(claude_archive.load(today), full=True)
        self.assertIn("SPY: news brief", full)
        self.assertIn("You manage one account.", full)


if __name__ == "__main__":
    unittest.main()
