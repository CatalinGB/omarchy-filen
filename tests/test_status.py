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

    def test_ok_false_fragment_is_unknown_but_keeps_checked_at(self):
        # A failed probe (offline) still carries the time it ran; the panel ages
        # its cache from that, so it must survive.
        doc = build_status(
            fragment={"ok": False, "quotaBytes": 10, "checkedAt": NOW - 5}
        )
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["checkedAt"], NOW - 5)

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


class AuthenticatedRotationTests(unittest.TestCase):
    """H07: the fragment's ``authenticated`` flag can veto a present blob."""

    def fresh(self, **extra):
        base = {"ok": True, "checkedAt": NOW - 5}
        base.update(extra)
        return base

    def test_blob_present_without_fragment_stays_authenticated(self):
        doc = build_status(fragment=None)
        self.assertTrue(doc["authenticated"])
        self.assertNotEqual(doc["statusText"], "Sign-in needed")

    def test_fresh_fragment_auth_false_marks_needs_auth(self):
        doc = build_status(
            fragment=self.fresh(authenticated=False, quotaKnown=False)
        )
        self.assertFalse(doc["authenticated"])
        self.assertEqual(doc["statusText"], "Sign-in needed")
        self.assertFalse(doc["quotaKnown"])

    def test_fresh_fragment_auth_true_stays_authenticated(self):
        doc = build_status(fragment=self.fresh(authenticated=True))
        self.assertTrue(doc["authenticated"])

    def test_fragment_without_auth_flag_stays_authenticated(self):
        doc = build_status(fragment=self.fresh())
        self.assertTrue(doc["authenticated"])

    def test_stale_auth_false_does_not_mark_needs_auth(self):
        doc = build_status(
            fragment={
                "ok": True,
                "authenticated": False,
                "checkedAt": NOW - 99999,
            }
        )
        self.assertTrue(doc["authenticated"])
        self.assertNotEqual(doc["statusText"], "Sign-in needed")

    def test_network_error_fragment_keeps_authenticated(self):
        # offline, not a rejected credential: no ``authenticated`` field
        doc = build_status(fragment={"ok": False, "checkedAt": NOW - 5})
        self.assertTrue(doc["authenticated"])
        self.assertNotEqual(doc["statusText"], "Sign-in needed")

    def test_missing_blob_beats_fresh_auth_true_fragment(self):
        doc = build_status(
            authenticated=False, fragment=self.fresh(authenticated=True)
        )
        self.assertFalse(doc["authenticated"])
        self.assertEqual(doc["statusText"], "Sign-in needed")

    def test_auth_failure_beats_failed_unit_state(self):
        doc = build_status(
            state="failed", fragment=self.fresh(authenticated=False)
        )
        self.assertFalse(doc["authenticated"])
        self.assertEqual(doc["statusText"], "Sign-in needed")

    def test_resolve_authenticated_directly(self):
        fresh_false = {"ok": False, "authenticated": False, "checkedAt": NOW - 1}
        self.assertFalse(
            status.resolve_authenticated(True, fresh_false, NOW)
        )
        self.assertFalse(status.resolve_authenticated(False, None, NOW))
        self.assertTrue(status.resolve_authenticated(True, None, NOW))
        self.assertTrue(
            status.resolve_authenticated(
                True,
                {"ok": True, "authenticated": False, "checkedAt": NOW - 99999},
                NOW,
            )
        )


class OfflineDegradedTests(unittest.TestCase):
    """H08: a stale/missing fragment is offline, not failed."""

    def test_stale_fragment_keeps_local_fields_and_checked_at(self):
        fragment = {
            "ok": True,
            "usedBytes": 500,
            "quotaBytes": 1000,
            "quotaKnown": True,
            "files": [{"name": "old.txt"}],
            "checkedAt": NOW - 99999,
        }
        doc = build_status(
            state="active", mounted=True, fragment=fragment
        )
        self.assertTrue(doc["installed"])
        self.assertTrue(doc["running"])
        self.assertEqual(doc["unitState"], "active")
        self.assertEqual(doc["mountPath"], MOUNT_ROOT)
        self.assertTrue(doc["authenticated"])
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["usedBytes"], 0)
        self.assertEqual(doc["quotaBytes"], 0)
        self.assertEqual(doc["files"], [])
        self.assertEqual(doc["checkedAt"], NOW - 99999)

    def test_missing_fragment_keeps_local_fields_and_uses_probe_time(self):
        doc = build_status(state="inactive", mounted=False, fragment=None)
        self.assertEqual(doc["unitState"], "inactive")
        self.assertEqual(doc["mountPath"], MOUNT_ROOT)
        self.assertFalse(doc["quotaKnown"])
        self.assertEqual(doc["checkedAt"], NOW)
        self.assertNotEqual(doc["statusText"], "Failed")

    def test_staleness_never_produces_failed(self):
        fragments = (
            None,
            {"ok": True, "checkedAt": NOW - 99999},
            {"ok": False, "checkedAt": NOW - 5},
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                doc = build_status(
                    state="inactive", mounted=False, fragment=fragment
                )
                self.assertEqual(doc["unitState"], "inactive")
                self.assertNotEqual(doc["statusText"], "Failed")

    def test_offline_does_not_flip_to_needs_auth(self):
        doc = build_status(
            state="inactive",
            fragment={"ok": False, "checkedAt": NOW - 99999},
        )
        self.assertTrue(doc["authenticated"])
        self.assertNotEqual(doc["statusText"], "Sign-in needed")


class MalformedFragmentTests(unittest.TestCase):
    """H22: no input shape may raise or yield non-finite JSON."""

    FRAGMENTS = (
        None,
        "not-a-dict",
        [],
        42,
        True,
        {},
        {"ok": True},
        {"ok": True, "checkedAt": NOW},
        {"ok": True, "checkedAt": "nope"},
        {"ok": True, "checkedAt": None},
        {"ok": True, "checkedAt": float("nan")},
        {"ok": True, "checkedAt": float("inf")},
        {"ok": True, "checkedAt": NOW, "usedBytes": float("inf")},
        {"ok": True, "checkedAt": NOW, "usedBytes": float("nan"), "quotaBytes": 1},
        {"ok": True, "checkedAt": NOW, "usedBytes": -5, "quotaBytes": -1, "quotaKnown": True},
        {"ok": True, "checkedAt": NOW, "usedBytes": 10 ** 400, "quotaBytes": 1, "quotaKnown": True},
        {"ok": True, "checkedAt": NOW, "quotaBytes": 100, "quotaKnown": True, "usagePercent": float("inf")},
        {"ok": True, "checkedAt": NOW, "quotaBytes": 100, "quotaKnown": True, "usagePercent": "25"},
        {"ok": True, "checkedAt": NOW, "quotaBytes": "huge", "quotaKnown": True},
        {"ok": True, "checkedAt": NOW, "quotaKnown": "yes", "quotaBytes": 100, "usagePercent": True},
        {"ok": True, "checkedAt": NOW, "files": "not-a-list"},
        {"ok": True, "checkedAt": NOW, "files": [None, 1, [], {"name": {"x": 1}}]},
        {
            "ok": True,
            "checkedAt": NOW,
            "files": [
                {
                    "name": {"nested": 1},
                    "path": ["a"],
                    "folder": None,
                    "modifiedTs": "bad",
                    "sizeBytes": float("inf"),
                }
            ],
        },
        {"ok": False, "checkedAt": NOW, "quotaBytes": 100},
        {"ok": False},
        {"checkedAt": True},
        {"ok": None, "checkedAt": NOW},
        {"authenticated": False, "checkedAt": NOW},
    )

    def test_fragments_never_raise_and_produce_strict_json(self):
        for fragment in self.FRAGMENTS:
            with self.subTest(fragment=repr(fragment)):
                doc = build_status(fragment=fragment)
                self.assertTrue(doc["ok"])
                self.assertIsInstance(doc["usedBytes"], int)
                self.assertIsInstance(doc["quotaBytes"], int)
                self.assertIsInstance(doc["usagePercent"], float)
                self.assertTrue(0.0 <= doc["usagePercent"] <= 100.0)
                text = json.dumps(doc, allow_nan=False)
                self.assertIsInstance(json.loads(text), dict)

    def test_merge_fragment_never_raises(self):
        for fragment in self.FRAGMENTS:
            with self.subTest(fragment=repr(fragment)):
                merged = status.merge_fragment(fragment, NOW)
                self.assertIsInstance(merged, dict)
                self.assertIn("quotaKnown", merged)
                json.dumps(merged, allow_nan=False)


class MalformedFileTests(unittest.TestCase):
    """H22: malformed ``api-status.json`` bytes cannot break the helper."""

    CASES = (
        b"",
        b"{",
        b"not json",
        b"\xff\xfe\x00\x01",
        b"[]",
        b'"a string"',
        b"null",
        b"42",
        b'{"usedBytes": -1, "quotaBytes": null}',
        b'{"checkedAt": 1e400}',
        b'{"ok": true, "checkedAt": 1, "files": [{"name": "\xff"}]}',
        b'{"ok": true, "checkedAt": 1e400, "usedBytes": 1e400}',
    )

    def run_main_with_fragment(self, raw):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "api-status.json").write_bytes(raw)
            with patch.object(status, "binary_present", return_value=True), patch.object(
                status, "credential_present", return_value=True
            ), patch.object(status, "unit_state", return_value="inactive"), patch.object(
                status, "is_mounted", return_value=False
            ), patch.object(status, "auto_mount_enabled", return_value=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = status.main(["--runtime-dir", tmp])
        return code, output.getvalue()

    def test_malformed_files_emit_one_valid_json_object(self):
        for raw in self.CASES:
            with self.subTest(raw=raw):
                code, out = self.run_main_with_fragment(raw)
                self.assertEqual(code, 0)
                lines = out.strip().splitlines()
                self.assertEqual(len(lines), 1)
                doc = json.loads(lines[0])
                self.assertIsInstance(doc, dict)

    def test_read_fragment_returns_none_or_dict(self):
        for raw in self.CASES:
            with self.subTest(raw=raw):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "api-status.json"
                    path.write_bytes(raw)
                    result = status.read_fragment(path)
                    self.assertTrue(result is None or isinstance(result, dict))


class MountinfoRobustnessTests(unittest.TestCase):
    """H22: unusual or non-UTF8 mount tables must not raise."""

    LINES = (
        "",
        "\n",
        "not enough fields\n",
        "36 29 0:42 / /tmp/a rw - fuse x rw\n",
        "36 29 0:42 / /tmp/with\\040space rw - fuse x rw\n",
        "garbage - - - -\n",
        "36 29 0:42 / /bad\\999escape rw - fuse x rw\n",
        "36 29 0:42 / /no-separator rw\n",
    )

    def test_unusual_lines_do_not_raise(self):
        for content in self.LINES:
            with self.subTest(content=content):
                with tempfile.NamedTemporaryFile(
                    "w", suffix=".mountinfo"
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    self.assertIsInstance(status.mounted_paths(handle.name), set)
                    self.assertIsInstance(
                        status.is_mounted("/tmp/a", handle.name), bool
                    )

    def test_non_utf8_mountinfo_does_not_raise(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".mountinfo") as handle:
            handle.write(b"36 29 0:42 / /tmp/\xff\xfe rw - fuse x rw\n")
            handle.flush()
            self.assertIsInstance(status.mounted_paths(handle.name), set)
            self.assertFalse(status.is_mounted("/tmp/x", handle.name))

    def test_missing_mountinfo_is_not_mounted(self):
        self.assertFalse(status.is_mounted("/tmp/a", "/nonexistent/mountinfo"))
        self.assertEqual(status.mounted_paths("/nonexistent/mountinfo"), set())


class MissingSystemctlTests(unittest.TestCase):
    """H22: an absent systemctl degrades to inactive/disabled."""

    def test_run_missing_binary_returns_failure(self):
        code, out = status.run(["omarchy-filen-nonexistent-binary-xyzzy"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    def test_unit_probes_survive_missing_systemctl(self):
        with patch.object(status, "run", return_value=(1, "")):
            self.assertEqual(status.unit_state(), "inactive")
            self.assertFalse(status.auto_mount_enabled())

    def test_main_contains_a_probe_exception(self):
        output = io.StringIO()
        with patch.object(status, "binary_present", return_value=True), patch.object(
            status, "credential_present", return_value=True
        ), patch.object(
            status, "auto_mount_enabled", return_value=False
        ), patch.object(
            status, "unit_state", side_effect=FileNotFoundError("systemctl")
        ), contextlib.redirect_stdout(output):
            code = status.main([])
        self.assertEqual(code, 0)
        doc = json.loads(output.getvalue().strip())
        self.assertFalse(doc["ok"])
        self.assertIsInstance(doc["checkedAt"], int)


class MainRobustnessTests(unittest.TestCase):
    """H22: ``main`` always emits exactly one JSON line and exits 0."""

    def run_main(self, argv):
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = status.main(argv)
        return code, output.getvalue()

    def test_bad_argv_emits_one_json_line(self):
        for argv in (
            ["--not-a-real-flag"],
            ["--api-max-age", "not-a-number"],
            ["--runtime-dir"],
            ["--mount-root", "/mnt/x", "--unknown"],
        ):
            with self.subTest(argv=argv):
                code, out = self.run_main(argv)
                self.assertEqual(code, 0)
                lines = out.strip().splitlines()
                self.assertEqual(len(lines), 1)
                doc = json.loads(lines[0])
                self.assertIsInstance(doc, dict)

    def test_non_serializable_collect_output_falls_back(self):
        class Weird:
            pass

        output = io.StringIO()
        with patch.object(
            status, "collect", return_value={"ok": True, "x": Weird()}
        ), contextlib.redirect_stdout(output):
            code = status.main([])
        self.assertEqual(code, 0)
        doc = json.loads(output.getvalue().strip())
        self.assertFalse(doc["ok"])
        self.assertIsInstance(doc["checkedAt"], int)

    def test_base_exception_from_collect_is_contained(self):
        output = io.StringIO()
        with patch.object(
            status, "collect", side_effect=KeyboardInterrupt()
        ), contextlib.redirect_stdout(output):
            code = status.main([])
        self.assertEqual(code, 0)
        doc = json.loads(output.getvalue().strip())
        self.assertFalse(doc["ok"])


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
