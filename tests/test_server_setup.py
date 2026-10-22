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


# Stands in for ssh-keygen: writes a key pair at the path after -f.
FAKE_KEYGEN = """#!/bin/bash
echo "ssh-keygen $*" >> "$CALLS"
while [ $# -gt 0 ]; do [ "$1" = -f ] && key="$2"; shift; done
echo "PRIVATE KEY" > "$key"
echo "ssh-ed25519 AAAAfakepublickey vanguard3-server" > "$key.pub"
"""

# Stands in for server/publish.sh --check: GitHub takes the key, or not.
FAKE_PUBLISH = """#!/bin/bash
echo "publish $*" >> "$CALLS"
if [ "${FAKE_PUBLISH_OK:-1}" = 1 ]; then
    echo "The deploy key may push."
    exit 0
fi
echo "GitHub did not take the summary (ERROR: read only)" >&2
exit 1
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

    def test_log_cannot_fill_the_disk(self):
        self.assertIn('max-size: "10m"', self.text)

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
        self.apt = tmp / "apt"
        (self.repo / "server").mkdir(parents=True)
        self.tools.mkdir()
        self.units.mkdir()
        self.apt.mkdir()
        for name in ("server/setup.sh", "server/docker-compose.yml",
                     "requirements-ibkr.txt", "ibkr_morning.sh"):
            shutil.copy(ROOT / name, self.repo / name)
        (self.repo / "server" / "publish.sh").write_text(FAKE_PUBLISH)
        self.keys = tmp / "ssh"
        fakes = {"id": FAKE_ID, "python3": FAKE_PYTHON3,
                 "fake-bridge": FAKE_BRIDGE, "ssh-keygen": FAKE_KEYGEN}
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
                    "UNIT_DIR": str(self.units), "APT_DIR": str(self.apt),
                    "KEY_DIR": str(self.keys)}

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
        # A run that hangs cannot block the next mornings.
        self.assertIn("TimeoutStartSec=40min", unit)

    def test_security_updates_restart_after_the_morning_run(self):
        self.setup(answers="DUTEST1\nsecret\n")
        apt = (self.apt / "52vanguard3-updates").read_text()
        self.assertIn('Unattended-Upgrade::Automatic-Reboot "true";', apt)
        self.assertIn('Automatic-Reboot-Time "11:00";', apt)

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

    def test_publish_makes_a_deploy_key(self):
        self.setup(answers="DUTEST1\nsecret\n")
        code, out, calls = self.setup("--publish", answers="\n\n")
        self.assertEqual(code, 0, out)
        key = self.keys / "vanguard3_publish"
        self.assertEqual(sum(c.startswith("ssh-keygen ") for c in calls), 1)
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.keys.stat().st_mode & 0o777, 0o700)
        # Exact steps on GitHub, with the public half of the key.
        self.assertIn("ssh-ed25519 AAAAfakepublickey", out)
        self.assertIn("https://github.com/mauritswessels/vanguard3-ibkr-data"
                      "/settings/keys", out)
        self.assertIn('Tick "Allow write access"', out)
        self.assertNotIn("PRIVATE KEY", out)
        settings = self.repo / "ibkr_morning.env"
        text = settings.read_text()
        self.assertIn('BRIDGE_ARGS="--port 4002"', text)     # kept
        self.assertIn("PUBLISH_REPO=git@github.com:mauritswessels/"
                      "vanguard3-ibkr-data.git\n", text)
        self.assertIn("PUBLISH_BRANCH=ibkr-data\n", text)
        self.assertIn(f"PUBLISH_KEY={key}\n", text)
        self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
        self.assertIn("publish --check", calls)
        # Nothing else is installed or restarted.
        self.assertFalse(any(c.startswith(("apt-get", "docker", "systemctl"))
                             for c in calls))
        self.assertIn("raw.githubusercontent.com/mauritswessels/"
                      "vanguard3-ibkr-data/ibkr-data/ibkr.json", out)

        # Again, for another repository: same key, settings replaced.
        code, _, calls = self.setup("--publish", answers="me/data\n\n")
        self.assertEqual(code, 0)
        self.assertFalse(any(c.startswith("ssh-keygen ") for c in calls))
        text = settings.read_text()
        self.assertEqual(text.count("PUBLISH_REPO="), 1)
        self.assertIn("PUBLISH_REPO=git@github.com:me/data.git\n", text)

    def test_publish_says_when_github_refuses_the_key(self):
        self.setup(answers="DUTEST1\nsecret\n")
        code, out, _ = self.setup("--publish", answers="\n\n",
                                  FAKE_PUBLISH_OK="0")
        self.assertEqual(code, 1)
        self.assertIn("ERROR: read only", out)
        self.assertIn("Allow write access", out)
        self.assertIn("setup.sh --publish", out)

    def test_publish_needs_the_setup_first(self):
        code, out, calls = self.setup("--publish", answers="\n\n")
        self.assertEqual(code, 1)
        self.assertIn("without --publish first", out)
        self.assertEqual(calls, [])

    def test_publish_refuses_a_bad_repository_name(self):
        self.setup(answers="DUTEST1\nsecret\n")
        code, out, calls = self.setup("--publish", answers="not a repo\n")
        self.assertEqual(code, 1)
        self.assertIn("doesn't look like owner/name", out)
        self.assertNotIn("PUBLISH_", (self.repo / "ibkr_morning.env")
                         .read_text())


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"),
                     "needs bash and git")
class PublishTest(unittest.TestCase):
    """server/publish.sh, pushing to a repository on this computer."""

    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo, self.remote = tmp / "Vanguard3", tmp / "data.git"
        (self.repo / "server").mkdir(parents=True)
        for name in ("publish.sh", "github_known_hosts"):
            shutil.copy(ROOT / "server" / name, self.repo / "server")
        subprocess.run(["git", "init", "--quiet", "--bare",
                        str(self.remote)], check=True)
        self.file = self.repo / "ibkr_logs" / "public" / "ibkr.json"
        self.file.parent.mkdir(parents=True)
        self.file.write_text('{"history": []}\n')
        self.settings(f"PUBLISH_REPO={self.remote}\n")

    def settings(self, text):
        (self.repo / "ibkr_morning.env").write_text(text)

    def publish(self, *args):
        done = subprocess.run(
            ["bash", str(self.repo / "server" / "publish.sh"), *args],
            cwd=self.repo, capture_output=True, text=True, timeout=60)
        return done.returncode, done.stdout + done.stderr

    def git(self, *args):
        return subprocess.run(["git", "--git-dir", str(self.remote), *args],
                              capture_output=True, text=True).stdout

    def test_publishes_to_its_own_branch(self):
        code, out = self.publish("ibkr_logs/public/ibkr.json")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.git("show", "ibkr-data:ibkr.json"),
                         '{"history": []}\n')
        self.assertIn("README.md", self.git("ls-tree", "--name-only",
                                            "ibkr-data"))
        self.assertEqual(self.git("branch", "--list").split(),
                         ["ibkr-data"])
        # The next morning replaces it: still a single small commit.
        self.file.write_text('{"history": [1]}\n')
        code, out = self.publish()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.git("show", "ibkr-data:ibkr.json"),
                         '{"history": [1]}\n')
        self.assertEqual(len(self.git("log", "--oneline", "ibkr-data")
                             .splitlines()), 1)

    def test_never_to_main(self):
        for branch in ("main", "master", "refs/heads/main", "bad..name"):
            with self.subTest(branch=branch):
                self.settings(f"PUBLISH_REPO={self.remote}\n"
                              f"PUBLISH_BRANCH={branch}\n")
                code, out = self.publish()
                self.assertEqual(code, 1)
                self.assertEqual(self.git("branch", "--list"), "")

    def test_check_changes_nothing(self):
        code, out = self.publish("--check")
        self.assertEqual(code, 0, out)
        self.assertIn("may push", out)
        self.assertEqual(self.git("branch", "--list"), "")

    def test_needs_settings_a_file_and_a_key(self):
        self.settings("")
        code, out = self.publish()
        self.assertEqual(code, 1)
        self.assertIn("setup.sh --publish", out)
        self.settings(f"PUBLISH_REPO={self.remote}\n")
        self.file.unlink()
        code, out = self.publish()
        self.assertEqual(code, 1)
        self.assertIn("No summary at", out)
        self.settings("PUBLISH_REPO=git@github.com:me/data.git\n"
                      "PUBLISH_KEY=/nowhere/key\n")
        code, out = self.publish("--check")
        self.assertEqual(code, 1)
        self.assertIn("No deploy key at /nowhere/key", out)

    def test_github_host_keys_are_pinned(self):
        """GitHub's published keys (api.github.com/meta), so the server
        never trusts an impostor on its first connection."""
        lines = (ROOT / "server" / "github_known_hosts").read_text().split("\n")
        kinds = [line.split()[1] for line in lines if line]
        self.assertEqual(kinds, ["ssh-ed25519", "ecdsa-sha2-nistp256",
                                 "ssh-rsa"])
        self.assertTrue(all(line.startswith("github.com ")
                            for line in lines if line))
        self.assertIn("StrictHostKeyChecking=yes",
                      (ROOT / "server" / "publish.sh").read_text())


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
