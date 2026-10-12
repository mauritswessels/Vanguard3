"""Run the IBKR bridge by itself every weekday morning (Mac only).

    python ibkr_schedule.py               # every weekday at 08:30
    python ibkr_schedule.py --time 08:15  # another time, on the Mac's clock
    python ibkr_schedule.py --remove      # stop the morning runs

Each run (``ibkr_morning.sh``) updates this folder from GitHub, places the
orders with ``ibkr_bridge.py --send`` and shows a notification with the
result. The Mac has to be on, with TWS logged in to Paper Trading; if the
Mac is asleep at that time, the run starts as soon as it wakes up. Details
go to ``ibkr_logs/morning.log``.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import config

LABEL = "ch.vanguard3.ibkr-bridge"
HERE = Path(__file__).resolve().parent
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def parse_time(text: str) -> tuple[int, int]:
    """``"08:30"`` -> ``(8, 30)``."""
    hour, _, minute = text.partition(":")
    h, m = int(hour), int(minute or 0)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"not a time of day: {text}")
    return h, m


def job(hour: int, minute: int, folder: Path = HERE) -> dict:
    """The macOS (launchd) job: ``ibkr_morning.sh`` Monday to Friday."""
    log = str(folder / "ibkr_logs" / "launchd.log")
    return {
        "Label": LABEL,
        "ProgramArguments": ["/bin/bash", str(folder / "ibkr_morning.sh")],
        "StartCalendarInterval": [
            {"Weekday": day, "Hour": hour, "Minute": minute}
            for day in range(1, 6)],
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True,
                          text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--time", default="08:30",
                        help="start time on the Mac's clock (default 08:30)")
    parser.add_argument("--remove", action="store_true",
                        help="stop the morning runs")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("This sets up the Mac's scheduler. On another "
                         "computer, run ibkr_morning.sh with its own "
                         "scheduler (for example cron).")
    try:
        hour, minute = parse_time(args.time)
    except ValueError:
        raise SystemExit(f"Use a time like 08:30, not {args.time!r}.")

    domain = f"gui/{os.getuid()}"
    launchctl("bootout", f"{domain}/{LABEL}")       # an older schedule
    if args.remove:
        PLIST.unlink(missing_ok=True)
        print("Stopped: the bridge no longer runs by itself.")
        return

    (HERE / "ibkr_logs").mkdir(exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(job(hour, minute)))
    done = launchctl("bootstrap", domain, str(PLIST))
    if done.returncode:
        raise SystemExit("The Mac did not accept the schedule: "
                         f"{done.stderr.strip() or done.returncode}")
    print(f"Done. Every weekday at {hour:02d}:{minute:02d} the bridge copies "
          f"'{config.IBKR_PARAMS['agent']}' into your paper account and "
          "shows a notification.\nKeep the Mac on and TWS logged in. "
          "Details: ibkr_logs/morning.log")


if __name__ == "__main__":
    main()
