#!/usr/bin/env python3

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


STATUS_PATH = Path(__file__).resolve().parents[1] / "bin" / "status"
LOADER = SourceFileLoader("filen_status", str(STATUS_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
status = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(status)


NOW = 1_700_000_000
MOUNT_ROOT = "/home/u/Filen"
FILEN_BIN = "/home/u/.local/share/omarchy-filen/bin/filen"
CREDENTIAL = "/home/u/.config/credstore.encrypted/filen-auth"
RUNTIME_DIR = "/run/user/1000/filen"


def build_status(
    installed=True,
    authenticated=True,
    state="inactive",
    mounted=False,
    fragment=None,
    now=NOW,
    api_max_age=status.API_MAX_AGE_SECONDS,
):
    """Drive build_status with every probe mocked."""
    with patch.object(status, "binary_present", return_value=installed), patch.object(
        status, "credential_present", return_value=authenticated
    ), patch.object(status, "unit_state", return_value=state), patch.object(
        status, "is_mounted", return_value=mounted
    ), patch.object(status, "read_fragment", return_value=fragment):
        return status.build_status(
            MOUNT_ROOT,
            FILEN_BIN,
            CREDENTIAL,
            RUNTIME_DIR,
            api_max_age=api_max_age,
            now=now,
        )


class StateContractTests(unittest.TestCase):
    def test_not_installed(self):
        doc = build_status(installed=False)
        self.assertEqual(doc["statusText"], "Not installed")
        self.assertFalse(doc["installed"])
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["usedBytes"], 0)
        self.assertEqual(doc["files"], [])
        self.assertEqual(doc["checkedAt"], NOW)

    def test_needs_auth(self):
        doc = build_status(authenticated=False)
        self.assertFalse(doc["authenticated"])
        self.assertEqual(doc["statusText"], "Sign-in needed")
        self.assertFalse(doc["running"])
        self.assertFalse(doc["quotaKnown"])

    def test_stopped(self):
        doc = build_status(state="inactive", mounted=False)
        self.assertTrue(doc["authenticated"])
        self.assertEqual(doc["statusText"], "Stopped")
        self.assertFalse(doc["running"])
        self.assertEqual(doc["unitState"], "inactive")

    def test_mounted(self):
        doc = build_status(state="active", mounted=True)
        self.assertTrue(doc["running"])
        self.assertEqual(doc["statusText"], "Mounted")

    def test_active_unit_without_mountpoint_still_running(self):
        doc = build_status(state="active", mounted=False)
        self.assertTrue(doc["running"])

    def test_failed(self):
        doc = build_status(state="failed")
        self.assertEqual(doc["unitState"], "failed")
        self.assertEqual(doc["statusText"], "Failed")


class FragmentMergeTests(unittest.TestCase):
    def test_missing_fragment_marks_api_unknown(self):
        doc = build_status(fragment=None)
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["usedBytes"], 0)
        self.assertEqual(doc["quotaBytes"], 0)
        self.assertEqual(doc["usagePercent"], 0.0)
        self.assertEqual(doc["files"], [])
        self.assertEqual(doc["checkedAt"], NOW)

    def test_unparseable_fragment_marks_api_unknown(self):
        doc = build_status(fragment="not-a-dict")
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["checkedAt"], NOW)

    def test_fragment_without_checked_at_is_unknown(self):
        doc = build_status(fragment={"ok": True, "quotaBytes": 10})
        self.assertFalse(doc["quotaKnown"])

    def test_ok_false_fragment_is_unknown(self):
        doc = build_status(
            fragment={"ok": False, "quotaBytes": 10, "checkedAt": NOW - 5}
        )
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["checkedAt"], NOW)

    def test_fresh_fragment_is_merged(self):
        fragment = {
            "ok": True,
            "usedBytes": 250,
            "quotaBytes": 1000,
            "usagePercent": 25.0,
            "quotaKnown": True,
            "files": [
                {
                    "name": "notes.md",
                    "path": "/home/u/Filen/notes.md",
                    "folder": "/",
                    "modifiedTs": NOW - 60,
                    "sizeBytes": 42,
                }
            ],
            "checkedAt": NOW - 30,
        }
        doc = build_status(fragment=fragment)
        self.assertTrue(doc["quotaKnown"])
        self.assertEqual(doc["usedBytes"], 250)
        self.assertEqual(doc["quotaBytes"], 1000)
        self.assertEqual(doc["usagePercent"], 25.0)
        self.assertEqual(doc["checkedAt"], NOW - 30)
        self.assertEqual(len(doc["files"]), 1)
        self.assertEqual(doc["files"][0]["name"], "notes.md")
        self.assertEqual(doc["files"][0]["sizeBytes"], 42)

    def test_usage_percent_derived_and_clamped(self):
        fragment = {
            "ok": True,
            "usedBytes": 500,
            "quotaBytes": 1000,
            "quotaKnown": True,
            "checkedAt": NOW - 5,
        }
        doc = build_status(fragment=fragment)
        self.assertEqual(doc["usagePercent"], 50.0)

    def test_stale_fragment_is_dropped_but_checked_at_surfaced(self):
        fragment = {
            "ok": True,
            "usedBytes": 500,
            "quotaBytes": 1000,
            "quotaKnown": True,
            "files": [{"name": "old.txt"}],
            "checkedAt": NOW - 9999,
        }
        doc = build_status(fragment=fragment)
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["usedBytes"], 0)
        self.assertEqual(doc["files"], [])
        self.assertEqual(doc["checkedAt"], NOW - 9999)

    def test_api_suppressed_without_credential(self):
        fragment = {
            "ok": True,
            "usedBytes": 500,
            "quotaBytes": 1000,
            "quotaKnown": True,
            "checkedAt": NOW - 5,
        }
        doc = build_status(authenticated=False, fragment=fragment)
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["usedBytes"], 0)


class ProbeTests(unittest.TestCase):
    def test_unit_state_parses_active_state(self):
        with patch.object(status, "run", return_value=(0, "ActiveState=active")):
            self.assertEqual(status.unit_state(), "active")

    def test_unit_state_defaults_inactive_on_failure(self):
        with patch.object(status, "run", return_value=(1, "")):
            self.assertEqual(status.unit_state(), "inactive")

    def test_mounted_paths_decodes_kernel_escapes(self):
        mountinfo = (
            "36 29 0:42 / /tmp/Cafe\\040Drive rw,nosuid,nodev "
            "- fuse.rclone filen: rw\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".mountinfo") as handle:
            handle.write(mountinfo)
            handle.flush()
            paths = status.mounted_paths(handle.name)
        self.assertEqual(paths, {"/tmp/Cafe Drive"})

    def test_is_mounted_compares_realpaths(self):
        mountinfo = "36 29 0:42 / /home/u/Filen rw,nosuid,nodev - fuse.rclone filen: rw\n"
        with tempfile.NamedTemporaryFile("w", suffix=".mountinfo") as handle:
            handle.write(mountinfo)
            handle.flush()
            self.assertTrue(status.is_mounted("/home/u/Filen", handle.name))
            self.assertFalse(status.is_mounted("/home/u/Other", handle.name))


class CliTests(unittest.TestCase):
    def test_main_emits_one_json_object(self):
        output = io.StringIO()
        with patch.object(status, "collect", return_value={"ok": True}), contextlib.redirect_stdout(
            output
        ):
            code = status.main([])
        self.assertEqual(code, 0)
        lines = output.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"ok": True})

    def test_main_emits_failure_document_on_exception(self):
        output = io.StringIO()
        with patch.object(status, "collect", side_effect=RuntimeError("boom")), contextlib.redirect_stdout(
            output
        ):
            code = status.main([])
        self.assertEqual(code, 0)
        doc = json.loads(output.getvalue())
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"], "boom")
        self.assertIsInstance(doc["checkedAt"], int)

    def test_main_emits_failure_document_on_bad_arguments(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = status.main(["--not-a-real-flag"])
        self.assertEqual(code, 0)
        doc = json.loads(output.getvalue())
        self.assertFalse(doc["ok"])
        self.assertIn("arguments", doc["error"])

    def test_collect_honors_mount_root(self):
        with patch.object(status, "binary_present", return_value=False), patch.object(
            status, "credential_present", return_value=False
        ), patch.object(status, "unit_state", return_value="inactive"), patch.object(
            status, "is_mounted", return_value=False
        ), patch.object(status, "read_fragment", return_value=None):
            doc = status.collect(["--mount-root", "/mnt/filen"])
        self.assertEqual(doc["mountPath"], "/mnt/filen")


if __name__ == "__main__":
    unittest.main()
