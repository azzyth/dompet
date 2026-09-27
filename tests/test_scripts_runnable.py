"""Every script must be runnable exactly as documented: `python scripts/<name>.py`.

Regression: executing a file directly puts the *script's* directory (``scripts/``) on
``sys.path``, not the repo root, so ``import dompet`` failed with ModuleNotFoundError
and every documented command in the README was broken. These tests shell out the same
way a user does — the in-process suite could not catch this because it imports the
package from the repo root.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("init_db.py", "load_rules.py", "poll_inbox.py", "seed_demo.py")


class ScriptsRunnableTest(unittest.TestCase):
    def test_scripts_import_the_package_and_reach_config_check(self):
        env = dict(os.environ)
        # Blank the DSN and drop IMAP so the scripts fail fast on configuration instead
        # of touching a real database or mailbox. Reaching that config error *proves*
        # the imports at the top of the file succeeded.
        env["DATABASE_URL"] = ""
        env.pop("IMAP_HOST", None)

        for script in SCRIPTS:
            with self.subTest(script=script):
                proc = subprocess.run(
                    [sys.executable, str(Path("scripts") / script)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=120,
                )
                self.assertNotIn(
                    "ModuleNotFoundError",
                    proc.stderr,
                    f"{script} cannot import the dompet package:\n{proc.stderr}",
                )
                self.assertTrue(
                    "DATABASE_URL is not set" in proc.stderr or "IMAP_HOST" in proc.stderr,
                    f"{script} did not reach its config check; stderr:\n{proc.stderr}",
                )

    def test_seed_demo_help_is_exactly_the_documented_command(self):
        proc = subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--days", proc.stdout)


if __name__ == "__main__":
    unittest.main()
