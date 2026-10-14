"""The cloud server setup (server/setup.sh and IB Gateway's settings), run
with fake system tools: nothing is installed and no server is touched."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "server" / "docker-compose.yml"

# Records every call of a system tool as "<tool> <arguments>".
RECORDER = """#!/bin/bash
echo "$(basename "$0") $*" >> "$CALLS"
"""

FAKE_ID = """#!/bin/bash
echo "${FAKE_UID:-0}"
"""

# Stands in for "python3 -m venv DIR": a venv whose python is a fake bridge.
FAKE_PYTHON3 = """#!/bin/bash
mkdir -p "$3/bin"
cp "$FAKE_BRIDGE" "$3/bin/python"
printf '#!/bin/bash\\necho "pip $*" >> "$CALLS"\\n' > "$3/bin/pip"
chmod +x "$3/bin/python" "$3/bin/pip"
"""

# The bridge's dry run; exits with the next code in FAKE_CODES (default 0).
FAKE_BRIDGE = """#!/bin/bash
echo "python $*" >> "$CALLS"
n=$(grep -c '^python ' "$CALLS")
code=$(echo "${FAKE_CODES:-0}" | cut -d, -f"$n")
if [ "${code:-0}" = 0 ]; then
    echo "Copying Team Manager: 3 markets, results of the 2026-10-12 close."
    echo "Dry run: nothing was sent."
    exit 0
fi
echo "Could not reach IB Gateway on port 4002 (TimeoutError)."
exit "$code"
"""


class ComposeTest(unittest.TestCase):
    text = COMPOSE.read_text()

    def test_paper_gateway_that_takes_orders(self):
        self.assertIn("image: ghcr.io/gnzsnz/ib-gateway:stable", self.text)
        self.assertIn("TRADING_MODE: paper", self.text)
        self.assertIn('READ_ONLY_API: "no"', self.text)
        self.assertIn("container_name: ib-gateway", self.text)

    def test_api_only_reachable_from_the_server(self):
        ports = re.findall(r'- "([^"]*:\d+)"', self.text)
        self.assertEqual(ports, ["127.0.0.1:4002:4004"])

    def test_password_comes_from_the_file_setup_writes(self):
        self.assertIn("file: ./ib_password.txt", self.text)
        self.assertIn("TWS_PASSWORD_FILE: /run/secrets/ib_password",
                      self.text)

    @unittest.skipUnless(shutil.which("docker"), "needs docker")
    def test_docker_accepts_it(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copy(COMPOSE, tmp)
        (tmp / "ib_password.txt").write_text("secret")
        done = subprocess.run(
            ["docker", "compose", "-f", str(tmp / "docker-compose.yml"),
             "config", "--quiet"],
            env={**os.environ, "TWS_USERID": "DUTEST1"},
            capture_output=True, text=True, timeout=60)
        if "is not a docker command" in done.stderr:
            self.skipTest("needs docker compose")
        self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class SetupScriptTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo, self.tools, self.units = (tmp / "Vanguard3", tmp / "bin",
                                             tmp / "units")
        (self.repo / "server").mkdir(parents=True)
        self.tools.mkdir()
        self.units.mkdir()
        for name in ("server/setup.sh", "server/docker-compose.yml",
                     "requirements-ibkr.txt", "ibkr_morning.sh"):
            shutil.copy(ROOT / name, self.repo / name)
        fakes = {"id": FAKE_ID, "python3": FAKE_PYTHON3,
                 "fake-bridge": FAKE_BRIDGE}
        for tool in ("apt-get", "timedatectl", "systemctl", "docker",
                     "chown", "curl", "sleep"):
            fakes[tool] = RECORDER
        for name, text in fakes.items():
            (self.tools / name).write_text(text)
            (self.tools / name).chmod(0o755)
        self.calls_file = tmp / "calls"
        self.env = {**os.environ, "PATH": f"{self.tools}:/usr/bin:/bin",
                    "CALLS": str(self.calls_file),
                    "FAKE_BRIDGE": str(self.tools / "fake-bridge"),
                    "UNIT_DIR": str(self.units)}

    def setup(self, *args, answers="", **env):
        """Run setup.sh, typing ``answers``; returns (exit code, output,
        the tool calls of this run)."""
        self.calls_file.write_text("")
        done = subprocess.run(
            ["bash", str(self.repo / "server" / "setup.sh"), *args],
            input=answers, capture_output=True, text=True, timeout=60,
            env={**self.env, **env})
        calls = self.calls_file.read_text().splitlines()
        return done.returncode, done.stdout + done.stderr, calls

    def test_first_run(self):
        code, out, calls = self.setup(answers="DUTEST1\n my secret$pw \n")
        self.assertEqual(code, 0, out)
        server = self.repo / "server"

        # The login is kept only on the server, for root and IB Gateway.
        self.assertEqual((server / ".env").read_text(), "TWS_USERID=DUTEST1\n")
        self.assertEqual((server / "ib_password.txt").read_text(),
                         " my secret$pw ")       # exactly as typed
        for name in (".env", "ib_password.txt"):
            self.assertEqual((server / name).stat().st_mode & 0o777, 0o600)
        self.assertIn(f"chown 1000:1000 {server}/ib_password.txt", calls)
        self.assertNotIn("my secret", out)

        settings = (self.repo / "ibkr_morning.env").read_text()
        self.assertIn('BRIDGE_ARGS="--port 4002"', settings)
        topic = re.search(r"NTFY_TOPIC=(vanguard3-[0-9a-f]{12})\n",
                          settings).group(1)
        self.assertIn(topic, out)

        self.assertIn(f"docker compose -f {server}/docker-compose.yml up -d "
                      "--force-recreate", calls)
        self.assertIn("systemctl daemon-reload", calls)
        self.assertIn("systemctl enable --now vanguard3-bridge.timer "
                      "vanguard3-update.timer", calls)
        self.assertIn(f"python {self.repo}/ibkr_bridge.py --port 4002",
                      calls)
        self.assertIn("Dry run: nothing was sent.", out)
        self.assertTrue(any(c.startswith("curl ") and
                            c.endswith(f"https://ntfy.sh/{topic}")
                            for c in calls))

    def test_weekday_units(self):
        self.setup(answers="DUTEST1\nsecret\n")
        unit = (self.units / "vanguard3-bridge.service").read_text()
        self.assertIn(f"ExecStart=/bin/bash {self.repo}/ibkr_morning.sh",
                      unit)
        timer = (self.units / "vanguard3-bridge.timer").read_text()
        self.assertIn("OnCalendar=Mon..Fri 08:30 Europe/Zurich", timer)
        self.assertIn("Persistent=true", timer)
        update = (self.units / "vanguard3-update.service").read_text()
        self.assertIn(f"WorkingDirectory={self.repo}/server", update)
        self.assertIn("ExecStart=/usr/bin/docker compose pull", update)

    @unittest.skipUnless(shutil.which("systemd-analyze"),
                         "needs systemd-analyze")
    def test_times_are_valid_for_systemd(self):
        self.setup(answers="DUTEST1\nsecret\n")
        for name in ("vanguard3-bridge.timer", "vanguard3-update.timer"):
            text = (self.units / name).read_text()
            when = re.search(r"OnCalendar=(.*)", text).group(1)
            done = subprocess.run(["systemd-analyze", "calendar", when],
                                  capture_output=True, text=True,
                                  timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_second_run_keeps_the_login(self):
        self.setup(answers="DUTEST1\nsecret\n")
        settings = (self.repo / "ibkr_morning.env").read_text()
        code, out, calls = self.setup()          # nothing typed this time
        self.assertEqual(code, 0, out)
        self.assertNotIn("Paper username", out)
        self.assertEqual((self.repo / "ibkr_morning.env").read_text(),
                         settings)
        self.assertIn(f"docker compose -f {self.repo}/server/"
                      "docker-compose.yml up -d", calls)

    def test_new_login(self):
        self.setup(answers="DUTEST1\nsecret\n")
        code, _, calls = self.setup("--login", answers="DUTEST2\nnew\n")
        self.assertEqual(code, 0)
        self.assertEqual((self.repo / "server" / ".env").read_text(),
                         "TWS_USERID=DUTEST2\n")
        self.assertTrue(any(c.endswith("--force-recreate") for c in calls))

    def test_gateway_that_never_answers(self):
        code, out, calls = self.setup(answers="DUTEST1\nwrong\n",
                                      FAKE_CODES="1,1,1,1,1,1")
        self.assertEqual(code, 1)
        self.assertEqual(sum(c.startswith("python ") for c in calls), 6)
        self.assertIn("IB Gateway did not answer", out)
        self.assertIn("setup.sh --login", out)
        self.assertIn("docker logs --tail 15 ib-gateway", calls)

    def test_empty_login_is_refused(self):
        code, out, _ = self.setup(answers="\n\n")
        self.assertEqual(code, 1)
        self.assertIn("doesn't look like a username", out)
        self.assertFalse((self.repo / "server" / ".env").exists())

    def test_needs_root(self):
        code, out, calls = self.setup(FAKE_UID="1000")
        self.assertEqual(code, 1)
        self.assertIn("run this as root", out)
        self.assertEqual(calls, [])


# Telegram's API as the helper sees it; every call is recorded.
FAKE_TELEGRAM_CURL = """#!/bin/bash
echo "curl $*" >> "$CALLS"
case "$*" in
  *getMe*) [ "${FAKE_TOKEN_OK:-1}" = 1 ] || exit 22; echo '{"ok":true}' ;;
  *getUpdates*) echo "${FAKE_UPDATES}" ;;
esac
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class TelegramTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo, tools = tmp / "Vanguard3", tmp / "bin"
        (self.repo / "server").mkdir(parents=True)
        tools.mkdir()
        shutil.copy(ROOT / "server" / "telegram.sh", self.repo / "server")
        (tools / "curl").write_text(FAKE_TELEGRAM_CURL)
        (tools / "curl").chmod(0o755)
        self.calls = tmp / "calls"
        self.env = {**os.environ, "PATH": f"{tools}:/usr/bin:/bin",
                    "CALLS": str(self.calls),
                    "FAKE_UPDATES": json.dumps({"result": [
                        {"message": {"chat": {"id": 7}}},
                        {"message": {"chat": {"id": 4242}}}]})}
        self.settings = self.repo / "ibkr_morning.env"

    def run_helper(self, answers, **env):
        done = subprocess.run(
            ["bash", str(self.repo / "server" / "telegram.sh")],
            input=answers, capture_output=True, text=True, timeout=30,
            env={**self.env, **env})
        return done.returncode, done.stdout + done.stderr

    def test_connects_and_keeps_other_settings(self):
        self.settings.write_text('BRIDGE_ARGS="--port 4002"\n'
                                 "TELEGRAM_CHAT_ID=1\n")
        code, out = self.run_helper("123:abc-DEF\n\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.settings.read_text(),
                         'BRIDGE_ARGS="--port 4002"\n'
                         "TELEGRAM_TOKEN=123:abc-DEF\nTELEGRAM_CHAT_ID=4242\n")
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("abc-DEF", out)
        self.assertIn("sendMessage", self.calls.read_text().splitlines()[-1])

    def test_refuses_a_bad_token(self):
        code, out = self.run_helper("not a token\n\n")
        self.assertEqual(code, 1)
        self.assertIn("doesn't look like a bot token", out)
        code, out = self.run_helper("123:abc\n\n", FAKE_TOKEN_OK="0")
        self.assertEqual(code, 1)
        self.assertIn("did not accept", out)
        self.assertFalse(self.settings.exists())

    def test_needs_a_message_to_the_bot(self):
        code, out = self.run_helper("123:abc\n\n",
                                    FAKE_UPDATES='{"result": []}')
        self.assertEqual(code, 1)
        self.assertIn("No message reached the bot", out)


if __name__ == "__main__":
    unittest.main()
