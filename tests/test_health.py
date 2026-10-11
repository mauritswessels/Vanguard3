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
