"""The weekly plain-language report: facts in, Claude's text saved."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import weekly_report as wr


def payload():
    days = ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12",
            "2026-10-13", "2026-10-14", "2026-10-15"]

    def agent(name, end, trades=(), **extra):
        eq = [[d, 100_000.0] for d in days[:-1]] + [[days[-1], end]]
        return {"name": name, "style": "test", "equity": eq,
                "stats": {"final_equity_chf": end,
                          "total_return": end / 100_000 - 1},
                "cash_chf": end / 2, "positions": [
                    {"ticker": "AAPL", "value_chf": end / 2, "pnl_pct": 0.01}],
                "trades": list(trades), "pending_orders": [], "ai": None,
                "team": None, **extra}
    return {"status": "live", "start": days[0], "agents": [
        agent("Trend Follower", 101_000.0, trades=[
            {"date": "2026-10-07", "side": "BUY", "ticker": "OLD",
             "reason": "before the week", "pnl_chf": 0},
            {"date": "2026-10-13", "side": "SELL", "ticker": "AAPL",
             "reason": "Trend ended", "pnl_chf": 250.4}]),
        agent("News Analyst (Opus)", 99_000.0, ai={
            "kind": "news", "model": "claude-opus-5-5",
            "market_view": "Rates worry markets", "status": "Decided"}),
    ]}


class WeeklyReportTest(unittest.TestCase):
    def test_facts_cover_the_last_five_sessions(self):
        f = wr.week_facts(payload())
        self.assertEqual((f["week_start"], f["week_end"]),
                         ("2026-10-09", "2026-10-15"))
        trend, opus = f["agents"]
        self.assertAlmostEqual(trend["week_return"], 0.01)
        self.assertEqual([t["ticker"] for t in trend["trades_this_week"]],
                         ["AAPL"])
        self.assertEqual(trend["trades_this_week"][0]["result_chf"], 250)
        self.assertEqual(trend["cash_share"], 0.5)
        self.assertEqual(opus["market_view"], "Rates worry markets")

    def test_report_is_saved_newest_first_and_emailed(self):
        reply = {"content": [{"type": "text", "text": "A calm week.\n\nOne lesson."}],
                 "model": "claude-sonnet-5-5", "usage": {"input_tokens": 10}}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(reply).encode()

        seen = {}

        def urlopen(req, timeout):
            seen["body"] = json.loads(req.data)
            return Response()

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "paper.json").write_text(json.dumps(payload()))
            out, issue = tmp / "weekly.json", tmp / "report.md"
            out.write_text(json.dumps({"reports": [
                {"week_end": "2026-10-08", "text": "older"}]}))
            argv = ["weekly_report.py", "--results", str(tmp / "paper.json"),
                    "--out", str(out), "--issue", str(issue)]
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
                    mock.patch.object(wr.urllib.request, "urlopen", urlopen), \
                    mock.patch("sys.argv", argv):
                wr.main()
            reports = json.loads(out.read_text())["reports"]
            body = issue.read_text()
        self.assertEqual([r["week_end"] for r in reports],
                         ["2026-10-15", "2026-10-08"])
        self.assertEqual(reports[0]["text"], "A calm week.\n\nOne lesson.")
        self.assertIn("A calm week.", body)
        self.assertIn("@Mits-Alt-F4", body)
        self.assertIn("Trend ended", seen["body"]["messages"][0]["content"])

    def test_no_key_is_an_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                wr.ask_claude({}, "claude-sonnet-5-5")


if __name__ == "__main__":
    unittest.main()
