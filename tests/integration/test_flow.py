#!/usr/bin/env python3
"""End-to-end hermetic tests for bin/setup and bin/status (H13).

Runnable on its own::

    python3 -m unittest discover -s tests/integration

No root, no network, no real systemd/FUSE: the harness puts fakes on PATH and
drives the real scripts inside a temporary HOME/XDG tree.
"""

import json
import os
import tempfile
import time
import unittest

try:  # discovered as part of the ``tests`` package (``-s tests``)
    from .harness import Harness, MARKER, FILEN_VERSION
except ImportError:  # discovered from inside ``tests/integration``
    from harness import Harness, MARKER, FILEN_VERSION


PLUGIN_UNITS = {
    "omarchy-filen-mount.service",
    "filen-status.service",
    "filen-status.timer",
}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.h = Harness(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()


class InstallFlowTest(_Base):
    def test_install_downloads_filen_populates_data_and_defaults(self):
        # The pinned rclone checksum cannot be forged offline, so pre-seed the
        # managed binary and let install fetch filen through the fake curl.
        self.h.seed_rclone()

        result = self.h.run("install")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.access(self.h.filen_bin, os.X_OK), "filen binary")
        self.assertEqual(
            (self.h.data_dir / "filen.version").read_text().strip(),
            FILEN_VERSION,
        )
        target = self.h.run("rclone-target").stdout.strip()
        self.assertTrue(
            os.access(self.h.rclone_dir / target, os.X_OK), "rclone seed"
        )

        settings = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn(f'MOUNT_ROOT="{self.h.home / "Filen"}"', settings)
        self.assertIn('CACHE_SIZE="4G"', settings)
        self.assertEqual(self.h.settings_file.stat().st_mode & 0o777, 0o600)

        units = self.h.units()
        self.assertEqual(set(units), PLUGIN_UNITS)
        for name, body in units.items():
            self.assertIn(MARKER, body, name)

        calls = "\n".join(self.h.calls())
        self.assertIn("curl", calls, "install should have downloaded filen")
        self.assertIn("daemon-reload", calls)
        self.assertIn("enable --now filen-status.timer", calls)

    def test_units_never_combine_runtime_directory_and_credential(self):
        self.h.seed_all()
        self.assertEqual(self.h.run("install").returncode, 0)

        for name, body in self.h.units().items():
            if "RuntimeDirectory=" in body:
                self.assertNotIn(
                    "LoadCredentialEncrypted=",
                    body,
                    f"{name} combines RuntimeDirectory with LoadCredentialEncrypted",
                )

        mount = self.h.units()["omarchy-filen-mount.service"]
        self.assertIn("LoadCredentialEncrypted=filen-auth", mount)
        self.assertNotIn("RuntimeDirectory=", mount)

    def test_install_is_idempotent_and_skips_second_download(self):
        self.h.seed_rclone()
        self.assertEqual(self.h.run("install").returncode, 0)
        first = self.h.units()
        curl_count = sum("curl " in line for line in self.h.calls())
        self.assertGreater(curl_count, 0)

        second = self.h.run("install")

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.h.units(), first)
        self.assertEqual(sum("curl " in line for line in self.h.calls()), curl_count)

    def test_install_preserves_existing_settings(self):
        self.h.seed_all()
        self.h.run("settings", "MOUNT_ROOT=/mnt/cloud", "CACHE_SIZE=2G")

        self.assertEqual(self.h.run("install").returncode, 0)

        settings = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn('MOUNT_ROOT="/mnt/cloud"', settings)
        self.assertIn('CACHE_SIZE="2G"', settings)

    def test_install_refuses_foreign_unit(self):
        self.h.seed_all()
        self.h.unit_dir.mkdir(parents=True, exist_ok=True)
        foreign = self.h.unit_dir / "omarchy-filen-mount.service"
        foreign.write_text("# someone else's unit\n", encoding="utf-8")

        result = self.h.run("install")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr)
        self.assertEqual(
            foreign.read_text(encoding="utf-8"), "# someone else's unit\n"
        )


class SettingsFlowTest(_Base):
    def test_settings_round_trip_mode_and_unknown_key(self):
        result = self.h.run("settings", "MOUNT_ROOT=/mnt/cloud", "CACHE_SIZE=2G")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.h.settings_file.stat().st_mode & 0o777, 0o600)
        text = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn(MARKER, text)
        self.assertIn('MOUNT_ROOT="/mnt/cloud"', text)
        self.assertIn('CACHE_SIZE="2G"', text)

        self.assertEqual(
            self.h.run("settings", "CACHE_SIZE=8G").returncode, 0
        )
        text = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn('MOUNT_ROOT="/mnt/cloud"', text)
        self.assertIn('CACHE_SIZE="8G"', text)

        bad = self.h.run("settings", "NOPE=1")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("unknown key", bad.stderr)

    def test_settings_defaults_when_missing(self):
        self.assertEqual(self.h.run("settings").returncode, 0)
        text = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn(f'MOUNT_ROOT="{self.h.home / "Filen"}"', text)
        self.assertIn('CACHE_SIZE="4G"', text)


class MountRunFlowTest(_Base):
    def test_mount_run_print_argv(self):
        root = self.h.tmp / "mount-root"
        self.h.run("settings", f"MOUNT_ROOT={root}", "CACHE_SIZE=2G")
        cfg = self.h.runtime_filen
        auth = self.h.tmp / "auth"

        result = self.h.run(
            "mount-run",
            "--print",
            "--config-dir",
            str(cfg),
            "--auth-config-path",
            str(auth),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                str(self.h.filen_bin),
                "--skip-update",
                "--config-dir",
                str(cfg),
                "--auth-config-path",
                str(auth),
                "mount",
                "--cache-size",
                "2G",
                str(root),
            ],
        )

    def test_mount_run_real_run_seeds_rclone_and_execs_filen(self):
        self.h.seed_all()
        target = self.h.run("rclone-target").stdout.strip()
        root = self.h.tmp / "mount-root"
        self.h.run("settings", f"MOUNT_ROOT={root}", "CACHE_SIZE=2G")
        cfg = self.h.runtime_filen
        auth = self.h.tmp / "auth"

        result = self.h.run(
            "mount-run", "--config-dir", str(cfg), "--auth-config-path", str(auth)
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        link = cfg / "rclone" / target
        self.assertTrue(link.is_symlink(), "rclone pre-seed symlink")
        self.assertEqual(
            os.readlink(link), str(self.h.rclone_dir / target)
        )
        self.assertEqual(
            self.h.argv_calls()[-1],
            " ".join(
                [
                    str(self.h.filen_bin),
                    "--skip-update",
                    "--config-dir",
                    str(cfg),
                    "--auth-config-path",
                    str(auth),
                    "mount",
                    "--cache-size",
                    "2G",
                    str(root),
                ]
            ),
        )


class FragmentFlowTest(_Base):
    def test_export_fragment_builds_contract_document(self):
        self.h.seed_filen()
        out = self.h.runtime_filen / "api-status.json"

        result = self.h.run(
            "export-fragment",
            "--filen",
            str(self.h.filen_bin),
            "--config-dir",
            str(self.h.runtime_filen),
            "--auth-config-path",
            str(self.h.tmp / "auth"),
            "--out",
            str(out),
            "--recents",
            "2",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        fragment = json.loads(out.read_text(encoding="utf-8"))
        self.assertIs(fragment["ok"], True)
        # ``authenticated`` is an H07 addition to the documented contract; assert
        # it only when present so the test tracks the committed fragment shape.
        if "authenticated" in fragment:
            self.assertIs(fragment["authenticated"], True)
        self.assertEqual(fragment["usedBytes"], 1000)
        self.assertEqual(fragment["quotaBytes"], 4000)
        self.assertIs(fragment["quotaKnown"], True)
        self.assertEqual(fragment["usagePercent"], 25.0)
        self.assertIsInstance(fragment["checkedAt"], int)
        self.assertEqual(
            [item["name"] for item in fragment["files"]], ["one.txt", "two.txt"]
        )
        self.assertEqual(fragment["files"][0]["folder"], "/a")
        self.assertEqual(fragment["files"][0]["modifiedTs"], 1767323045)
        self.assertEqual(fragment["files"][1]["sizeBytes"], 20)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_export_fragment_failure_is_valid_json(self):
        failing = self.h.tmp / "filen-fail"
        failing.write_text("#!/usr/bin/env bash\necho boom >&2\nexit 1\n")
        failing.chmod(0o755)
        out = self.h.runtime_filen / "api-status.json"

        result = self.h.run(
            "export-fragment",
            "--filen",
            str(failing),
            "--config-dir",
            str(self.h.runtime_filen),
            "--out",
            str(out),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        fragment = json.loads(out.read_text(encoding="utf-8"))
        self.assertIs(fragment["ok"], False)
        self.assertIn("error", fragment)
        self.assertIsInstance(fragment["checkedAt"], int)


class PrerequisiteFlowTest(_Base):
    def test_check_reports_prerequisites(self):
        result = self.h.run("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok      fuse3", result.stdout)
        self.assertIn("ok      python3", result.stdout)
        self.assertIn("systemd 261", result.stdout)

    def test_doctor_reports_health_and_gates_on_missing_credential(self):
        self.h.seed_all()
        self.assertEqual(self.h.run("install").returncode, 0)
        self.h.set_unit_state("active")

        unhealthy = self.h.run("doctor")
        self.assertNotEqual(unhealthy.returncode, 0)
        self.assertIn("missing credential", unhealthy.stdout)

        self.h.write_credential()
        healthy = self.h.run("doctor")
        self.assertEqual(healthy.returncode, 0, healthy.stdout)
        self.assertIn("doctor: healthy", healthy.stdout)

    def test_check_fails_when_a_prerequisite_is_missing(self):
        # Force an unmet prerequisite deterministically: report a systemd that
        # is older than the required 256, regardless of what the host provides.
        creds = self.h.fake_bin / "systemd-creds"
        creds.write_text(
            '#!/usr/bin/env bash\n'
            'if [[ "${1:-}" == "--version" ]]; then echo "systemd 250 (250.0)"; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        creds.chmod(0o755)

        result = self.h.run("check")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing systemd", result.stdout)


class StatusFlowTest(_Base):
    def status(self):
        result = self.h.run_status()
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_not_installed(self):
        doc = self.status()
        self.assertIs(doc["ok"], True)
        self.assertIs(doc["installed"], False)
        self.assertEqual(doc["statusText"], "Not installed")
        self.assertIs(doc["quotaKnown"], False)

    def test_needs_auth_without_credential(self):
        self.h.seed_filen()
        doc = self.status()
        self.assertIs(doc["installed"], True)
        self.assertIs(doc["authenticated"], False)
        self.assertEqual(doc["statusText"], "Sign-in needed")

    def test_stopped(self):
        self.h.seed_filen()
        self.h.write_credential()
        self.h.set_unit_state("inactive")
        doc = self.status()
        self.assertIs(doc["authenticated"], True)
        self.assertIs(doc["running"], False)
        self.assertEqual(doc["statusText"], "Stopped")

    def test_mounted(self):
        self.h.seed_filen()
        self.h.write_credential()
        self.h.set_unit_state("active")
        doc = self.status()
        self.assertIs(doc["running"], True)
        self.assertEqual(doc["statusText"], "Mounted")
        self.assertEqual(doc["unitState"], "active")

    def test_failed_is_reported_as_offline(self):
        self.h.seed_filen()
        self.h.write_credential()
        self.h.set_unit_state("failed")
        doc = self.status()
        self.assertEqual(doc["unitState"], "failed")
        self.assertEqual(doc["statusText"], "Failed")

    def test_offline_fragment_keeps_local_state_and_drops_quota(self):
        self.h.seed_filen()
        self.h.write_credential()
        self.h.set_unit_state("active")
        self.h.api_fragment.parent.mkdir(parents=True, exist_ok=True)
        self.h.api_fragment.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": "network unreachable",
                    "checkedAt": int(time.time()),
                }
            ),
            encoding="utf-8",
        )

        doc = self.status()
        self.assertIs(doc["running"], True)
        self.assertIs(doc["authenticated"], True)
        self.assertEqual(doc["statusText"], "Mounted")
        self.assertIs(doc["quotaKnown"], False)
        self.assertEqual(doc["usedBytes"], 0)

    def test_fresh_fragment_is_merged(self):
        self.h.seed_filen()
        self.h.write_credential()
        self.h.set_unit_state("active")
        now = int(time.time())
        self.h.api_fragment.parent.mkdir(parents=True, exist_ok=True)
        self.h.api_fragment.write_text(
            json.dumps(
                {
                    "ok": True,
                    "authenticated": True,
                    "usedBytes": 250,
                    "quotaBytes": 1000,
                    "usagePercent": 25.0,
                    "quotaKnown": True,
                    "files": [
                        {"name": "notes.md", "path": "/notes.md", "folder": "/",
                         "modifiedTs": now - 60, "sizeBytes": 42}
                    ],
                    "checkedAt": now - 5,
                }
            ),
            encoding="utf-8",
        )

        doc = self.status()
        self.assertIs(doc["quotaKnown"], True)
        self.assertEqual(doc["usedBytes"], 250)
        self.assertEqual(doc["quotaBytes"], 1000)
        self.assertEqual(doc["usagePercent"], 25.0)
        self.assertEqual(doc["files"][0]["name"], "notes.md")

    def test_autostart_flag_reflected(self):
        self.h.seed_filen()
        self.h.write_credential()
        self.h.set_unit_enabled(True)
        doc = self.status()
        self.assertIs(doc["autoMount"], True)


class UninstallFlowTest(_Base):
    def setUp(self):
        super().setUp()
        self.h.seed_all()
        self.assertEqual(self.h.run("install").returncode, 0)
        self.h.write_credential()
        self.h.mount_root.mkdir(parents=True, exist_ok=True)

    def test_uninstall_keeps_credential_and_restores_filesystem(self):
        result = self.h.run("uninstall")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.h.units(), {})
        self.assertFalse(self.h.data_dir.exists())
        self.assertFalse((self.h.config / "omarchy-filen").exists())
        self.assertTrue(self.h.credential.exists())
        self.assertFalse(self.h.mount_root.exists())

    def test_uninstall_purge_removes_credential(self):
        result = self.h.run("uninstall", "--purge")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.h.units(), {})
        self.assertFalse(self.h.credential.exists())

    def test_uninstall_keeps_a_nonempty_mount_folder(self):
        (self.h.mount_root / "keep.txt").write_text("data", encoding="utf-8")

        self.assertEqual(self.h.run("uninstall").returncode, 0)

        self.assertTrue((self.h.mount_root / "keep.txt").exists())

    def test_uninstall_refuses_foreign_unit(self):
        foreign = self.h.unit_dir / "omarchy-filen-mount.service"
        foreign.write_text("# someone else's unit\n", encoding="utf-8")

        result = self.h.run("uninstall")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr)
        self.assertTrue(foreign.exists())


if __name__ == "__main__":
    unittest.main()
