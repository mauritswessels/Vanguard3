"""The bridge's weekday-morning run: the macOS job and ibkr_morning.sh
(the same script runs on the cloud server)."""

import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ibkr_schedule as schedule

ROOT = Path(__file__).resolve().parent.parent

FAKE_PYTHON = """#!/bin/bash
# Stands in for ".venv/bin/python ibkr_bridge.py --send" (and the chart,
# and the summary for the website).
if [ "$1" = ibkr_summary.py ]; then
    echo "summary" >> "$PUBLISHED"
    echo "${FAKE_SUMMARY:-Summary for the website saved.}"
    exit "${FAKE_SUMMARY_CODE:-0}"
fi
if [ "$1" = telegram_chart.py ]; then
    echo png > "$2"
    [ "$3" = --why ] && echo "Why the top 3 hold what they hold" > "$4"
    [ "$5" = --trades ] && echo "Trades on 12 Oct" > "$6"
    echo "The race, day 5"
    exit 0
fi
echo "$@" >> "$CALLS"
n=$(wc -l < "$CALLS" | tr -d ' ')
code=$(echo "$FAKE_CODES" | cut -d, -f"$n")
if [ "$code" = 0 ]; then
    echo "Copying Team Manager: 3 markets, results of the 2026-10-12 close."
    [ -n "$FAKE_WARNING" ] && echo "$FAKE_WARNING"
    echo "Done: 2 of 3 orders placed; not accepted: EWZ."
    echo "Saved to ibkr_logs/2026-10-13.json"
else
    echo "${FAKE_FAILURE:-Could not reach TWS on port 7497.
Is TWS open and logged in to Paper Trading?}"
fi
exit "$code"
"""

FAKE_PUBLISH = """#!/bin/bash
echo "publish $*" >> "$PUBLISHED"
if [ "${FAKE_PUBLISH_CODE:-0}" = 0 ]; then
    echo "Published: https://raw.githubusercontent.com/me/data/ibkr-data/ibkr.json"
    exit 0
fi
echo "git@github.com: Permission denied (publickey)." >&2
echo "GitHub did not take the summary (Permission denied)" >&2
exit 1
"""

FAKE_OSASCRIPT = """#!/bin/bash
for last; do :; done
printf '%s' "$last" > "$NOTIFIED"
"""

FAKE_DOCKER = """#!/bin/bash
echo "$@" >> "$DOCKER"
# IB Gateway's start time: long ago, unless the test says otherwise.
[ "$1" = inspect ] && echo "${FAKE_STARTED:-2026-10-13T05:00:00.5Z}"
exit 0
"""

FAKE_CURL = """#!/bin/bash
printf '%s\\n' "$@" > "$CURLED"
printf '%s\\n' "$@" >> "$CURLED.all"
"""


class JobTest(unittest.TestCase):
    def test_times(self):
        self.assertEqual(schedule.parse_time("08:30"), (8, 30))
        self.assertEqual(schedule.parse_time("7"), (7, 0))
        for bad in ("25:00", "08:75", "soon"):
            with self.assertRaises(ValueError):
                schedule.parse_time(bad)

    def test_job_runs_the_script_on_weekdays(self):
        job = schedule.job(8, 15, Path("/Users/m/Vanguard3"))
        job = plistlib.loads(plistlib.dumps(job))
        self.assertEqual(job["ProgramArguments"],
                         ["/bin/bash", "/Users/m/Vanguard3/ibkr_morning.sh"])
        self.assertEqual([(d["Weekday"], d["Hour"], d["Minute"])
                          for d in job["StartCalendarInterval"]],
                         [(day, 8, 15) for day in range(1, 6)])

    def test_install_and_remove(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        plist = tmp / "LaunchAgents" / f"{schedule.LABEL}.plist"
        calls = []

        def launchctl(*args):
            calls.append(args[0])
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.multiple(schedule, PLIST=plist, HERE=tmp,
                                 launchctl=launchctl), \
                mock.patch.object(schedule.sys, "platform", "darwin"):
            with mock.patch("sys.argv", ["ibkr_schedule.py"]):
                schedule.main()
            self.assertEqual(calls, ["bootout", "bootstrap"])
            job = plistlib.loads(plist.read_bytes())
            self.assertEqual(job["StartCalendarInterval"][0]["Hour"], 8)
            with mock.patch("sys.argv", ["ibkr_schedule.py", "--remove"]):
                schedule.main()
            self.assertFalse(plist.exists())


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class MorningScriptTest(unittest.TestCase):
    def run_script(self, codes, settings=None, failure=None, docker=False,
                   publish=False, **env_extra):
        """Run ibkr_morning.sh with fake tools; the bridge exits with
        ``codes`` on its attempts. ``settings`` is the text of
        ibkr_morning.env, if any. Returns (notification, calls, log); the
        ntfy request, if one was sent, is in ``self.curled``. ``failure``
        replaces the bridge's error text; with ``docker`` the IB Gateway
        container exists and its commands land in ``self.docker``; with
        ``publish`` server/publish.sh exists, and the summary and publish
        steps land in ``self.published``."""
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        repo, tools = tmp / "Vanguard3", tmp / "bin"
        (repo / ".venv" / "bin").mkdir(parents=True)
        tools.mkdir()
        shutil.copy(ROOT / "ibkr_morning.sh", repo)
        if settings is not None:
            (repo / "ibkr_morning.env").write_text(settings)
        fakes = {repo / ".venv" / "bin" / "python": FAKE_PYTHON,
                 repo / ".venv" / "bin" / "pip": "#!/bin/bash\n",
                 tools / "git": "#!/bin/bash\n",
                 tools / "sleep": "#!/bin/bash\n",
                 tools / "osascript": FAKE_OSASCRIPT,
                 tools / "curl": FAKE_CURL}
        if docker:
            fakes[tools / "docker"] = FAKE_DOCKER
        if publish:
            (repo / "server").mkdir()
            fakes[repo / "server" / "publish.sh"] = FAKE_PUBLISH
        for path, text in fakes.items():
            path.write_text(text)
            path.chmod(0o755)
        env = {**os.environ, "PATH": f"{tools}:/usr/bin:/bin",
               "CALLS": str(tmp / "calls"), "NOTIFIED": str(tmp / "notified"),
               "CURLED": str(tmp / "curled"), "DOCKER": str(tmp / "docker"),
               "PUBLISHED": str(tmp / "published"),
               "FAKE_CODES": ",".join(map(str, codes))}
        if failure:
            env["FAKE_FAILURE"] = failure
        env.update(env_extra)
        done = subprocess.run(["bash", str(repo / "ibkr_morning.sh")],
                              env=env, timeout=30)
        self.assertEqual(done.returncode, codes[-1])
        curled = tmp / "curled"
        self.curled = (curled.read_text().splitlines() if curled.exists()
                       else None)
        dock = tmp / "docker"
        self.docker = dock.read_text().splitlines() if dock.exists() else []
        every = tmp / "curled.all"
        self.all_curled = every.read_text() if every.exists() else ""
        published = tmp / "published"
        self.published = (published.read_text().splitlines()
                          if published.exists() else [])
        return ((tmp / "notified").read_text(),
                (tmp / "calls").read_text().splitlines(),
                (repo / "ibkr_logs" / "morning.log").read_text())

    def test_success_is_reported(self):
        note, calls, log = self.run_script([0])
        self.assertEqual(note, "Done: 2 of 3 orders placed; "
                               "not accepted: EWZ.")
        self.assertEqual(calls, ["ibkr_bridge.py --send"])
        self.assertIn("Copying Team Manager", log)

    def test_tries_again_after_a_failure(self):
        note, calls, _ = self.run_script([1, 0])
        self.assertEqual(len(calls), 2)
        self.assertTrue(note.startswith("Done:"))

    def test_gives_up_after_three_tries(self):
        note, calls, log = self.run_script([1, 1, 1])
        self.assertEqual(len(calls), 3)
        self.assertEqual(note, "Morning run failed: Is TWS open and "
                               "logged in to Paper Trading?")
        self.assertEqual(log.count("Could not reach TWS"), 3)

    def test_restarts_a_silent_ib_gateway(self):
        silent = ("IB Gateway stopped answering for 60 seconds: it is "
                  "probably logged out of IBKR")
        note, calls, log = self.run_script([1, 1, 1], failure=silent,
                                           docker=True)
        self.assertEqual(len(calls), 3)
        # Restarted before each new try, not after the last one.
        started = "inspect -f {{.State.StartedAt}} ib-gateway"
        self.assertEqual(self.docker, [started, "restart ib-gateway"] * 2)
        self.assertEqual(note, f"Morning run failed: {silent}")
        self.assertIn("Restarting IB Gateway", log)

    def test_lets_a_starting_ib_gateway_log_in(self):
        """Just after the server boots (or a restart) it is still logging
        in: restarting it then would only start the login over."""
        silent = "Could not reach IB Gateway on port 4002 (refused)."
        now = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                             capture_output=True, text=True).stdout.strip()
        _, calls, log = self.run_script([1, 1, 0], failure=silent,
                                        docker=True, FAKE_STARTED=now)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("restart ib-gateway", self.docker)
        self.assertIn("letting it log in", log)

    def test_no_new_try_when_the_bridge_refuses(self):
        note, calls, _ = self.run_script(
            [3], failure="The agent's targets add up to 114% of its account, "
                         "which can't be right, so no orders were sent.")
        self.assertEqual(len(calls), 1)
        self.assertTrue(note.startswith("Morning run failed: The agent's "
                                        "targets add up to 114%"))

    def test_warnings_come_along(self):
        warning = ("Warning: the orders for SOON.SW sent on 2026-10-12 did "
                   "not fill; they are sent again.")
        note, _, _ = self.run_script([0], FAKE_WARNING=warning)
        self.assertEqual(note, "Done: 2 of 3 orders placed; not accepted: "
                               f"EWZ.\n{warning}")

    def test_healthchecks_ping(self):
        self.run_script([0], "HEALTHCHECK_URL=https://hc-ping.com/abc\n")
        self.assertIn("https://hc-ping.com/abc\n", self.all_curled)
        self.run_script([1, 1, 1], "HEALTHCHECK_URL=https://hc-ping.com/abc\n")
        self.assertIn("https://hc-ping.com/abc/fail", self.all_curled)

    def test_leaves_docker_alone_for_other_problems(self):
        self.run_script([1, 0], docker=True)
        self.assertEqual(self.docker, [])

    def test_without_settings_no_phone_message(self):
        self.run_script([0])
        self.assertIsNone(self.curled)

    def test_server_settings(self):
        settings = ('BRIDGE_ARGS="--port 4002"\n'
                    "NTFY_TOPIC=vanguard3-test\n")
        _, calls, _ = self.run_script([0], settings)
        self.assertEqual(calls, ["ibkr_bridge.py --send --port 4002"])
        self.assertEqual(self.curled[-1], "https://ntfy.sh/vanguard3-test")
        self.assertIn("Done: 2 of 3 orders placed; not accepted: EWZ.",
                      self.curled)
        self.assertIn("Priority: default", self.curled)

    def test_failure_rings_the_phone(self):
        self.run_script([1, 1, 1], "NTFY_TOPIC=vanguard3-test\n")
        self.assertIn("Priority: high", self.curled)
        self.assertIn("Morning run failed: Is TWS open and logged in to "
                      "Paper Trading?", self.curled)

    PUBLISH = ("PUBLISH_REPO=git@github.com:me/data.git\n"
               "HEALTHCHECK_URL=https://hc-ping.com/abc\n")

    def test_publishes_the_summary_after_the_orders(self):
        note, calls, log = self.run_script([0], self.PUBLISH, publish=True)
        self.assertEqual(self.published,
                         ["summary", "publish ibkr_logs/public/ibkr.json"])
        self.assertEqual(note, "Done: 2 of 3 orders placed; "
                               "not accepted: EWZ.")
        self.assertEqual(calls, ["ibkr_bridge.py --send"])
        self.assertIn("Published: https://raw.githubusercontent.com", log)
        self.assertLess(log.index("Done:"), log.index("Summary for"))

    def test_a_publishing_problem_only_adds_a_line(self):
        for fail, why in (
                ({"FAKE_PUBLISH_CODE": "1"},
                 "GitHub did not take the summary (Permission denied)"),
                ({"FAKE_SUMMARY_CODE": "1",
                  "FAKE_SUMMARY": "The results are now of 2026-10-13."},
                 "The results are now of 2026-10-13.")):
            with self.subTest(why=why):
                # The run still counts as a success (exit code 0).
                note, calls, _ = self.run_script([0], self.PUBLISH,
                                                 publish=True, **fail)
                self.assertEqual(note, "Done: 2 of 3 orders placed; not "
                                       "accepted: EWZ.\nCould not publish "
                                       "the account summary for the "
                                       f"website: {why}")
                self.assertEqual(calls, ["ibkr_bridge.py --send"])
                self.assertIn("https://hc-ping.com/abc\n", self.all_curled)
                self.assertNotIn("https://hc-ping.com/abc/fail",
                                 self.all_curled)

    def test_publishes_nothing_after_a_failed_run(self):
        self.run_script([1, 1, 1], self.PUBLISH, publish=True)
        self.assertEqual(self.published, [])

    def test_publishes_nothing_unless_set_up(self):
        self.run_script([0], publish=True)
        self.assertEqual(self.published, [])

    def test_telegram(self):
        self.run_script([0], "TELEGRAM_TOKEN=123:abc\nTELEGRAM_CHAT_ID=42\n")
        sent = self.all_curled
        self.assertIn("https://api.telegram.org/bot123:abc/sendMessage", sent)
        self.assertIn("text=Vanguard3: Done: 2 of 3 orders placed; "
                      "not accepted: EWZ.", sent)
        # Then the race chart, with its caption.
        self.assertIn("https://api.telegram.org/bot123:abc/sendPhoto", sent)
        self.assertIn("photo=@ibkr_logs/race.png", sent)
        self.assertIn("caption=The race, day 5", sent)
        # Then why the top three hold what they hold, then the trades.
        self.assertEqual(self.curled[-1],
                         "https://api.telegram.org/bot123:abc/sendMessage")
        self.assertIn("chat_id=42", self.curled)
        self.assertIn("text@ibkr_logs/why.txt", sent)
        self.assertIn("text@ibkr_logs/trades.txt", self.curled)
        self.assertLess(sent.index("sendPhoto"), sent.index("why.txt"))
        self.assertLess(sent.index("why.txt"), sent.index("trades.txt"))


if __name__ == "__main__":
    unittest.main()
