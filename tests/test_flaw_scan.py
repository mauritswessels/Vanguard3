"""The flaw scan: each check catches what it is meant to, and the project
as it is passes all of them (offline)."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import flaw_scan
from data_manager import load_market_data
from engine.broker import Order
from engine.simulator import Simulator, build_accounts
from models import make_agent


def saved_state() -> dict:
    """A real saved state: a few sessions of two accounts."""
    market = load_market_data("synthetic", pd.Timestamp("2025-01-01"),
                              pd.Timestamp("2026-03-31"), cache_dir=None,
                              seed=4)
    sim = Simulator(market, build_accounts(
        market, [make_agent("trend"), make_agent("benchmark")]))
    sim.run(market.calendar[-40:-1])
    acc = sim.accounts[1]
    acc.broker.submit(Order("QQQ", "BUY", 3, sim.last_date))
    return json.loads(json.dumps(sim.to_dict(), default=str))


class AccountsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.state = saved_state()

    def problems(self, change=None):
        s = copy.deepcopy(self.state)
        if change:
            change(s)
        return flaw_scan.state_problems(s)

    def test_a_simulated_state_adds_up(self):
        self.assertEqual(self.problems(), [])
        self.assertTrue(any(a["portfolio"]["trades"]
                            for a in self.state["accounts"]))

    def test_cash_that_does_not_match_the_fills(self):
        def change(s):
            s["accounts"][1]["portfolio"]["cash"] += 5
        [found] = self.problems(change)
        self.assertIn("Buy & Hold SPY: its cash is", found)

    def test_negative_cash(self):
        def change(s):
            pf = s["accounts"][1]["portfolio"]
            pf["trades"][0]["cash_flow_chf"] -= pf["cash"] + 100
            pf["cash"] = -100.0
        self.assertIn("below zero", self.problems(change)[0])

    def test_holdings_that_do_not_match_the_fills(self):
        def change(s):
            s["accounts"][1]["portfolio"]["positions"][0]["quantity"] += 1
        self.assertIn("do not match its fills", self.problems(change)[0])

    def test_a_split_is_followed(self):
        def change(s):
            pf = s["accounts"][1]["portfolio"]
            pos = pf["positions"][0]
            pf["events"].append({"date": s["last_date"], "kind": "split",
                                 "ticker": pos["ticker"], "ratio": 2.0,
                                 "shares_before": pos["quantity"],
                                 "shares": 2 * pos["quantity"], "chf": 0.0})
            pos["quantity"] *= 2
        self.assertEqual(self.problems(change), [])

    def test_bad_waiting_orders(self):
        def change(s):
            orders = s["accounts"][1]["pending_orders"]
            orders.append(dict(orders[0]))                  # twice
            orders.append({"ticker": "XYZ", "side": "HOLD", "quantity": 0,
                           "created": "2099-01-01"})
            orders.append({"ticker": "SPY", "side": "BUY", "quantity": 2,
                           "created": "2099-01-01", "kind": "close"})
        found = " ".join(self.problems(change))
        for words in ("two waiting orders for QQQ", "not on the watchlist",
                      "neither a buy nor a sell", "has 0 shares",
                      "after the last session"):
            self.assertIn(words, found)
        # The midday check's order for today's close is made after the last
        # session: that is fine.
        self.assertNotIn("SPY was made", found)

    def test_a_target_that_is_not_a_number(self):
        def change(s):
            s["accounts"][0]["agent_state"]["targets"] = {
                "SPY": {"weight": None}}
        self.assertIn("not a number", self.problems(change)[0])

    def test_an_account_value_that_stops_early(self):
        def change(s):
            eq = s["accounts"][0]["portfolio"]["equity"]
            del eq[max(eq)]
        self.assertIn("stops on", self.problems(change)[0])

    def test_two_accounts_with_one_name(self):
        def change(s):
            s["accounts"].append(copy.deepcopy(s["accounts"][0]))
        self.assertIn("Two accounts are called", self.problems(change)[0])


class ProjectTest(unittest.TestCase):

    def test_the_project_as_it_is_passes(self):
        self.assertEqual(flaw_scan.config_problems(), [])
        self.assertEqual(flaw_scan.bridge_problems(), [])
        self.assertEqual(flaw_scan.workflow_problems(), [])
        self.assertEqual(flaw_scan.data_problems(), [])
        self.assertEqual(flaw_scan.secret_problems(), [])

    def test_the_paper_only_check_is_watched(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "ibkr_bridge.py"
            bridge.write_text("accounts = ib.managedAccounts()\n")
            self.assertEqual(len(flaw_scan.bridge_problems(bridge)), 1)
            bridge.write_text('ok = [a for a in x if a.startswith("D")]\n')
            self.assertEqual(flaw_scan.bridge_problems(bridge), [])

    def test_secrets_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("server/.env\n")
            (root / "notes.md").write_text(
                "key sk-ant-api03-" + "x" * 30 + "\n")
            (root / "fine.md").write_text("token 123:abc\n")
            found = flaw_scan.secret_problems(
                root, ["notes.md", "fine.md", "ibkr_logs/blocked.json"])
            text = " ".join(found)
            self.assertIn("no longer leaves out ibkr_morning.env", text)
            self.assertIn("notes.md holds what looks like an Anthropic", text)
            self.assertIn("ibkr_logs/blocked.json is in the repository", text)
            self.assertNotIn("fine.md", text)

    def test_a_workflow_that_pushes_outside_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "ok.yml").write_text(
                "concurrency:\n  group: paper-trading\nsteps: git push\n")
            (folder / "bad.yml").write_text("steps: git push\n")
            (folder / "quiet.yml").write_text("steps: echo hi\n")
            found = flaw_scan.workflow_problems(folder)
            self.assertEqual(len(found), 1)
            self.assertIn("bad.yml", found[0])

    def test_a_scheduled_workflow_that_fails_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "loud.yml").write_text(
                "on:\n  schedule:\n    - cron: '0 6 * * 6'\n"
                "steps: gh issue comment 21\n")
            (folder / "silent.yml").write_text(
                "on:\n  schedule:\n    - cron: '0 6 * * 6'\n"
                "steps: echo hi\n")
            (folder / "by_hand.yml").write_text("on: workflow_dispatch\n")
            found = flaw_scan.workflow_problems(folder)
            self.assertEqual(len(found), 1)
            self.assertIn("silent.yml runs on a schedule", found[0])

    def test_data_a_browser_cannot_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "good.json").write_text('{"a": null}')
            (folder / "bad.json").write_text('{"a": NaN}')
            found = flaw_scan.data_problems(folder)
            self.assertEqual(len(found), 1)
            self.assertIn("bad.json", found[0])


if __name__ == "__main__":
    unittest.main()
