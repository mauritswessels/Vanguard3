"""The health check behind the alert emails."""

import unittest

import pandas as pd

from health_check import latest_session, problems


def state(last, news_decided):
    return {"last_date": last, "accounts": [
        {"agent": "trend", "agent_state": {}},
        {"agent": "news", "agent_state": {"decided": news_decided,
                                          "status": "No decision today: x"}}]}


class HealthTest(unittest.TestCase):
    def test_up_to_date_is_quiet(self):
        self.assertEqual(problems(state("2026-10-09", "2026-10-09"),
                                  pd.Timestamp("2026-10-09")), [])

    def test_missed_run_and_news_failure_are_reported(self):
        found = problems(state("2026-10-08", "2026-10-07"),
                         pd.Timestamp("2026-10-09"))
        self.assertEqual(len(found), 2)
        self.assertIn("Thu 08 Oct", found[0])
        self.assertIn("No decision today", found[1])

    def test_opus_twin_failure_is_reported_by_name(self):
        s = state("2026-10-09", "2026-10-09")
        s["accounts"].append({"agent": "news_opus", "name": "News Analyst (Opus)",
                              "agent_state": {"decided": None,
                                              "status": "No decision today: y"}})
        found = problems(s, pd.Timestamp("2026-10-09"))
        self.assertEqual(len(found), 1)
        self.assertIn("News Analyst (Opus) made no decision", found[0])

    def test_orders_that_did_not_go_through_are_reported(self):
        s = state("2026-10-20", "2026-10-20")
        s["accounts"][0].update(name="Volatility Protected", activity=[
            {"date": "2026-10-19", "rejected": [
                {"ticker": "MA", "side": "BUY", "quantity": 1,
                 "created": "2026-10-16", "why": "insufficient cash"}]},
            {"date": "2026-10-20", "rejected": [
                {"ticker": "SAP.DE", "side": "BUY", "quantity": 54,
                 "created": "2026-10-12", "why": "expired"}]}])
        found = problems(s, pd.Timestamp("2026-10-20"))
        self.assertEqual(found, [
            "Volatility Protected: the order to buy 54 SAP.DE (from Mon 12 "
            "Oct) did not go through: its market did not open for a week."])

    def test_failed_midday_check_is_reported(self):
        s = state("2026-10-19", "2026-10-19")
        s["accounts"][1]["name"] = "News Analyst"
        s["accounts"][1]["agent_state"]["midday"] = {
            "time": "2026-10-20T15:12+00:00", "ok": False,
            "status": "Midday check failed: Claude refused (400): Your "
                      "credit balance is too low"}
        today = pd.Timestamp("2026-10-20 15:20", tz="UTC")
        found = problems(s, pd.Timestamp("2026-10-19"), today, midday=True)
        self.assertEqual(len(found), 1)
        self.assertIn("News Analyst's midday check failed", found[0])
        self.assertIn("credit balance is too low", found[0])
        # Yesterday's failure is old news; the evening check ignores it.
        later = pd.Timestamp("2026-10-21 15:20", tz="UTC")
        self.assertEqual(problems(s, pd.Timestamp("2026-10-19"), later,
                                  midday=True), [])
        self.assertEqual(problems(s, pd.Timestamp("2026-10-19")), [])

    def test_latest_session(self):
        before_close = pd.Timestamp("2026-10-12 15:00", tz="UTC")  # Monday
        self.assertEqual(latest_session(before_close),
                         pd.Timestamp("2026-10-09"))
        holiday = [pd.Timestamp(d) for d in ("2026-10-08", "2026-10-09")]
        after_close = pd.Timestamp("2026-10-12 22:00", tz="UTC")
        self.assertEqual(latest_session(after_close),
                         pd.Timestamp("2026-10-12"))
        self.assertEqual(latest_session(after_close, holiday),
                         pd.Timestamp("2026-10-09"))


if __name__ == "__main__":
    unittest.main()
