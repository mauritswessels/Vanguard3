"""The bridge's weekday-morning run: the macOS job and ibkr_morning.sh."""

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
# Stands in for ".venv/bin/python ibkr_bridge.py --send".
echo "$@" >> "$CALLS"
n=$(wc -l < "$CALLS" | tr -d ' ')
code=$(echo "$FAKE_CODES" | cut -d, -f"$n")
if [ "$code" = 0 ]; then
    echo "Copying Team Manager: 3 markets, results of the 2026-10-12 close."
    echo "Done: 2 of 3 orders placed; not accepted: EWZ."
    echo "Saved to ibkr_logs/2026-10-13.json"
else
    echo "Could not reach TWS on port 7497."
    echo "Is TWS open and logged in to Paper Trading?"
fi
exit "$code"
"""

FAKE_OSASCRIPT = """#!/bin/bash
for last; do :; done
printf '%s' "$last" > "$NOTIFIED"
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
    def run_script(self, codes):
        """Run ibkr_morning.sh with fake tools; the bridge exits with
        ``codes`` on its attempts. Returns (notification, calls, log)."""
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        repo, tools = tmp / "Vanguard3", tmp / "bin"
        (repo / ".venv" / "bin").mkdir(parents=True)
        tools.mkdir()
        shutil.copy(ROOT / "ibkr_morning.sh", repo)
        fakes = {repo / ".venv" / "bin" / "python": FAKE_PYTHON,
                 repo / ".venv" / "bin" / "pip": "#!/bin/bash\n",
                 tools / "git": "#!/bin/bash\n",
                 tools / "sleep": "#!/bin/bash\n",
                 tools / "osascript": FAKE_OSASCRIPT}
        for path, text in fakes.items():
            path.write_text(text)
            path.chmod(0o755)
        env = {**os.environ, "PATH": f"{tools}:/usr/bin:/bin",
               "CALLS": str(tmp / "calls"), "NOTIFIED": str(tmp / "notified"),
               "FAKE_CODES": ",".join(map(str, codes))}
        done = subprocess.run(["bash", str(repo / "ibkr_morning.sh")],
                              env=env, timeout=30)
        self.assertEqual(done.returncode, codes[-1])
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


if __name__ == "__main__":
    unittest.main()
