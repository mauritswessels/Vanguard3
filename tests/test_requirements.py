"""The pinned package lists: every package pinned and fingerprinted, and
the same version wherever both lists need it."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ("requirements.txt", "requirements-ibkr.txt")


def pins(name: str) -> dict[str, tuple[str, int]]:
    """Package -> (version, number of hashes) in one lock file."""
    text = (ROOT / name).read_text()
    out = {}
    # A requirement starts at the beginning of a line; its hashes follow on
    # indented continuation lines up to the next requirement.
    for block in re.split(r"\n(?=[A-Za-z])", "\n" + text):
        first = block.strip().splitlines()[0] if block.strip() else ""
        if not first or first.startswith("#"):
            continue
        m = re.match(r"([A-Za-z0-9_.-]+)==(\S+)", first)
        if not m:
            raise AssertionError(f"{name}: not pinned with ==: {first}")
        out[m.group(1).lower()] = (m.group(2), block.count("--hash=sha256:"))
    return out


class RequirementsTest(unittest.TestCase):
    def test_every_package_is_pinned_with_hashes(self):
        for name in FILES:
            found = pins(name)
            self.assertTrue(found, name)
            for package, (version, hashes) in found.items():
                self.assertGreater(hashes, 0, f"{name}: {package} has no hash")

    def test_the_lists_hold_what_the_code_asks_for(self):
        main, ibkr = pins(FILES[0]), pins(FILES[1])
        for package in ("yfinance", "pandas", "numpy"):
            self.assertIn(package, main)
        for package in ("ib-async", "certifi", "matplotlib"):
            self.assertIn(package, ibkr)
        self.assertNotIn("pandas", ibkr)      # the server needs no pandas

    def test_shared_packages_have_the_same_version(self):
        # The Mac's .venv installs both lists; they must not fight.
        main, ibkr = pins(FILES[0]), pins(FILES[1])
        for package in main.keys() & ibkr.keys():
            self.assertEqual(main[package][0], ibkr[package][0], package)


if __name__ == "__main__":
    unittest.main()
