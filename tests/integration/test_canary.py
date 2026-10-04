#!/usr/bin/env python3
"""Canary test: no plaintext credential ever persists (H20).

Runs a (fake) ``setup provision`` with a fake ``filen`` that holds a unique
canary secret, then greps the plugin config/data/runtime dirs, the temporary
staging tree, and the captured output for that secret. The only place the
canary is allowed to appear is the test's own recorder file, which the fake
``systemd-creds`` writes to prove the encryption step actually received the
plaintext; the test deletes it before the final sweep.
"""

import tempfile
import unittest
import uuid

try:
    from .harness import Harness
except ImportError:
    from harness import Harness


class NoPlaintextCredentialCanaryTest(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.h = Harness(self._tempdir.name)
        self.canary = "CANARY-" + uuid.uuid4().hex
        self.h.env["FILEN_FAKE_CANARY"] = self.canary
        self.h.seed_all()

    def tearDown(self):
        self._tempdir.cleanup()

    # ------------------------------------------------------------- helpers

    def grep_canary(self):
        """Paths under the temp tree whose bytes contain the canary."""
        needle = self.canary.encode()
        hits = []
        for path in sorted(self.h.tmp.rglob("*")):
            if not path.is_file():
                continue
            try:
                if needle in path.read_bytes():
                    hits.append(str(path.relative_to(self.h.tmp)))
            except OSError:
                continue
        return hits

    def assert_no_canary(self, context=""):
        hits = self.grep_canary()
        self.assertEqual(hits, [], f"canary persisted ({context}): {hits}")

    # --------------------------------------------------------------- tests

    def test_canary_never_persists_across_provision_and_uninstall(self):
        install = self.h.run("install")
        self.assertEqual(install.returncode, 0, install.stderr)

        provision = self.h.run_pty("provision")
        self.assertEqual(provision.returncode, 0, provision.stdout[-2000:])
        self.assertTrue(self.h.credential.exists(), "credential blob")

        # Sanity check: the encryption step really did receive the plaintext.
        self.assertTrue(self.h.creds_record.exists())
        self.assertIn(
            self.canary, self.h.creds_record.read_text(encoding="utf-8")
        )

        # The staged plaintext export must be gone from TMPDIR entirely.
        leftovers = [
            str(p) for p in self.h.tmpdir.rglob("*") if "auth-config" in p.name
        ]
        self.assertEqual(leftovers, [], "plaintext export left behind")

        # The recorded input is the test's own instrument, not plugin state;
        # drop it and prove the canary survives nowhere else.
        self.h.creds_record.unlink()
        self.assert_no_canary("after provision")
        for output in (install.stdout, install.stderr, provision.stdout):
            self.assertNotIn(self.canary, output, "canary leaked into output")

        # Uninstall without purge keeps the encrypted blob but no plaintext.
        self.assertEqual(self.h.run("uninstall").returncode, 0)
        self.assertTrue(self.h.credential.exists())
        self.assert_no_canary("after uninstall")

        # Purge removes the blob and still no plaintext anywhere.
        self.assertEqual(self.h.run("uninstall", "--purge").returncode, 0)
        self.assertFalse(self.h.credential.exists())
        self.assert_no_canary("after uninstall --purge")

    def test_plaintext_temp_is_removed_even_when_reprovisioning(self):
        self.assertEqual(self.h.run("install").returncode, 0)

        first = self.h.run_pty("provision")
        self.assertEqual(first.returncode, 0, first.stdout[-2000:])
        self.h.creds_record.unlink()

        # Rotate: run provision again; the new staging dir must also be gone.
        second = self.h.run_pty("provision")
        self.assertEqual(second.returncode, 0, second.stdout[-2000:])
        self.h.creds_record.unlink()

        self.assertEqual(
            [p for p in self.h.tmpdir.rglob("*") if "auth-config" in p.name], []
        )
        self.assert_no_canary("after re-provision")


if __name__ == "__main__":
    unittest.main()
