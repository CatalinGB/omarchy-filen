#!/usr/bin/env python3
"""Tests for bin/setup.

Written with unittest (stdlib) so the suite runs without extra dependencies;
pytest collects unittest.TestCase classes unchanged.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "bin" / "setup"
MARKER = "# Managed by the filen.storage Omarchy plugin; do not edit."

FAKE_FILEN = """#!/usr/bin/env bash
case "$*" in
  *"stat /a/one.txt")
    echo '{"name":"one.txt","type":"file","size":10,"modified":"2026-01-02T03:04:05Z","created":null,"uuid":"u1"}' ;;
  *"stat /a/two.txt")
    echo '{"name":"two.txt","type":"file","size":20,"modified":1700000000,"created":null,"uuid":"u2"}' ;;
  *"list-recents")
    echo '{"directories":["/a"],"files":["/a/one.txt","/a/two.txt"]}' ;;
  *"stat /")
    echo '{"type":"drive","usedStorage":1000,"totalStorage":4000,"files":3,"directories":1}' ;;
  *)
    echo "unexpected: $*" >&2; exit 1 ;;
esac
"""


def write_exec(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


class Harness:
    def __init__(self, root):
        self.tmp = Path(root)
        self.home = self.tmp / "home"
        self.config = self.tmp / "config"
        self.data = self.tmp / "data"
        self.runtime = self.tmp / "run"
        self.fake_bin = self.tmp / "fake-bin"
        for directory in (self.home, self.config, self.data, self.runtime, self.fake_bin):
            directory.mkdir(parents=True, exist_ok=True)

        self.exec_log = self.tmp / "exec.log"
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.config),
                "XDG_DATA_HOME": str(self.data),
                "XDG_RUNTIME_DIR": str(self.runtime),
                "PATH": f"{self.fake_bin}{os.pathsep}{self.env.get('PATH', '')}",
                "OMARCHY_FILEN_MOUNT_ROOT": str(self.home / "Filen"),
                "OMARCHY_FILEN_CACHE_SIZE": "4G",
                "OMARCHY_FILEN_RECENTS": "2",
                "SYSTEMCTL_LOG": str(self.exec_log),
            }
        )
        self._install_fakes()

    @property
    def unit_dir(self):
        return self.config / "systemd" / "user"

    @property
    def data_dir(self):
        return self.data / "omarchy-filen"

    @property
    def filen_bin(self):
        return self.data_dir / "bin" / "filen"

    @property
    def credential(self):
        return self.config / "credstore.encrypted" / "filen-auth"

    @property
    def settings_file(self):
        return self.config / "omarchy-filen" / "settings.conf"

    def _install_fakes(self):
        write_exec(
            self.fake_bin / "systemctl",
            '#!/usr/bin/env bash\necho "systemctl $*" >> "$SYSTEMCTL_LOG"\nexit 0\n',
        )
        write_exec(
            self.fake_bin / "systemd-creds",
            '#!/usr/bin/env bash\nif [[ "$1" == "--version" ]]; then echo "systemd 261 (261.1)"; fi\nexit 0\n',
        )
        write_exec(self.fake_bin / "fusermount3", "#!/usr/bin/env bash\nexit 0\n")
        write_exec(
            self.fake_bin / "curl",
            '#!/usr/bin/env bash\necho "curl $*" >> "$SYSTEMCTL_LOG"\nexit 1\n',
        )

    def seed_binaries(self):
        target = self.run("rclone-target").stdout.strip()
        write_exec(self.filen_bin, "#!/usr/bin/env bash\nexit 0\n")
        write_exec(self.data_dir / "rclone" / target, "#!/usr/bin/env bash\nexit 0\n")
        (self.data_dir / "filen.version").write_text("0.2.8\n", encoding="utf-8")

    def calls(self):
        if not self.exec_log.exists():
            return []
        return self.exec_log.read_text(encoding="utf-8").splitlines()

    def run(self, *args):
        return subprocess.run(
            [str(SETUP), *args],
            capture_output=True,
            text=True,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )


class SetupTest(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.h = Harness(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()

    # ----------------------------------------------------------- pure helpers

    def test_asset_name_gnu(self):
        result = self.h.run("asset-name", "x86_64", "gnu")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "filen-cli-0.2.8-x86_64-unknown-linux-gnu")

    def test_asset_name_arm_musl(self):
        result = self.h.run("asset-name", "aarch64", "musl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "filen-cli-0.2.8-aarch64-unknown-linux-musl")

    def test_asset_name_rejects_unknown_architecture(self):
        result = self.h.run("asset-name", "sparc", "gnu")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported architecture", result.stderr)

    def test_rclone_target_arch_mapping(self):
        self.assertEqual(
            self.h.run("rclone-target", "x86_64").stdout.strip(),
            "rclone-v1.74.2-linux-amd64",
        )
        self.assertEqual(
            self.h.run("rclone-target", "aarch64").stdout.strip(),
            "rclone-v1.74.2-linux-arm64",
        )

    def test_marker_detection(self):
        managed = self.h.tmp / "managed.service"
        managed.write_text(MARKER + "\n[Service]\n", encoding="utf-8")
        foreign = self.h.tmp / "foreign.service"
        foreign.write_text("[Service]\n", encoding="utf-8")

        self.assertEqual(self.h.run("check-marker", str(managed)).returncode, 0)
        self.assertNotEqual(self.h.run("check-marker", str(foreign)).returncode, 0)
        self.assertNotEqual(
            self.h.run("check-marker", str(self.h.tmp / "absent.service")).returncode, 0
        )

    # ------------------------------------------------------------ unit render

    def test_mount_unit_render(self):
        result = self.h.run("render-unit", "filen-mount")
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = result.stdout
        for token in (
            MARKER,
            "Type=simple",
            "After=graphical-session.target",
            "PartOf=graphical-session.target",
            "WantedBy=graphical-session.target",
            "Restart=on-failure",
            "KillMode=mixed",
            "RuntimeDirectory=filen",
            "RuntimeDirectoryMode=0700",
            "LoadCredentialEncrypted=filen-auth",
            "ConditionPathExists=%E/credstore.encrypted/filen-auth",
            "mount-run --config-dir %t/filen --auth-config-path %d/filen-auth",
            "ExecStartPre=/usr/bin/ln -sf",
        ):
            self.assertIn(token, unit)
        rclone = self.h.run("rclone-target").stdout.strip()
        self.assertIn(f"%t/filen/{rclone}", unit)
        # The mount root and cache size are now live settings, not baked in.
        self.assertNotIn("--cache-size", unit)
        self.assertNotIn(str(self.h.home / "Filen"), unit)
        self.assertIn(str(SETUP), unit)

    def test_status_unit_render(self):
        unit = self.h.run("render-unit", "filen-status.service").stdout
        self.assertIn(MARKER, unit)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("LoadCredentialEncrypted=filen-auth", unit)
        self.assertIn("ConditionPathExists=%E/credstore.encrypted/filen-auth", unit)
        self.assertIn("export-fragment", unit)
        self.assertIn("--out %t/filen/api-status.json", unit)
        self.assertIn("ExecStartPre=/usr/bin/mkdir -p %t/filen", unit)
        # The mount unit owns RuntimeDirectory=filen; the oneshot must not
        # declare it or stopping it would delete the live mount's tmpfs.
        self.assertNotIn("RuntimeDirectory=", unit)

    def test_status_timer_render(self):
        unit = self.h.run("render-unit", "filen-status.timer").stdout
        self.assertIn(MARKER, unit)
        self.assertIn("OnUnitActiveSec=10min", unit)
        self.assertIn("Unit=filen-status.service", unit)
        self.assertIn("WantedBy=timers.target", unit)

    def test_unknown_unit_is_rejected(self):
        self.assertNotEqual(self.h.run("render-unit", "definitely-not-a-unit").returncode, 0)

    # -------------------------------------------------------------- settings

    def test_settings_round_trip_writes_marker_and_mode(self):
        root = self.h.tmp / "custom-root"
        result = self.h.run("settings", f"MOUNT_ROOT={root}", "CACHE_SIZE=2G")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.h.settings_file.exists())
        self.assertEqual(self.h.settings_file.stat().st_mode & 0o777, 0o600)
        text = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn(MARKER, text)
        self.assertIn(f'MOUNT_ROOT="{root}"', text)
        self.assertIn('CACHE_SIZE="2G"', text)

    def test_settings_preserves_unspecified_keys(self):
        root = self.h.tmp / "root"
        self.h.run("settings", f"MOUNT_ROOT={root}", "CACHE_SIZE=2G")

        result = self.h.run("settings", "CACHE_SIZE=8G")

        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn(f'MOUNT_ROOT="{root}"', text)
        self.assertIn('CACHE_SIZE="8G"', text)

    def test_settings_defaults_when_file_missing(self):
        result = self.h.run("settings")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.h.settings_file.read_text(encoding="utf-8")
        self.assertIn(f'MOUNT_ROOT="{self.h.home / "Filen"}"', text)
        self.assertIn('CACHE_SIZE="4G"', text)

    def test_settings_rejects_unknown_key(self):
        result = self.h.run("settings", "NOPE=1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown key", result.stderr)

    def test_mount_run_argument_construction(self):
        root = self.h.tmp / "mount-root"
        self.h.run("settings", f"MOUNT_ROOT={root}", "CACHE_SIZE=2G")

        result = self.h.run(
            "mount-run",
            "--print",
            "--config-dir",
            "/run/user/1000/filen",
            "--auth-config-path",
            "/run/creds/filen-auth",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                str(self.h.filen_bin),
                "--skip-update",
                "--config-dir",
                "/run/user/1000/filen",
                "--auth-config-path",
                "/run/creds/filen-auth",
                "mount",
                "--cache-size",
                "2G",
                str(root),
            ],
        )

    def test_mount_run_expands_leading_tilde(self):
        self.h.run("settings", "MOUNT_ROOT=~/Cloud", "CACHE_SIZE=4G")

        result = self.h.run(
            "mount-run",
            "--print",
            "--config-dir",
            "/tmp/cfg",
            "--auth-config-path",
            "/tmp/auth",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], str(self.h.home / "Cloud"))

    def test_mount_run_requires_config_dir_and_auth(self):
        result = self.h.run("mount-run", "--print", "--config-dir", "/tmp/cfg")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--auth-config-path is required", result.stderr)

    # ---------------------------------------------------------------- install

    def test_install_is_idempotent(self):
        self.h.seed_binaries()

        first = self.h.run("install")
        self.assertEqual(first.returncode, 0, first.stderr)
        rendered = {path.name: path.read_text(encoding="utf-8") for path in self.h.unit_dir.iterdir()}
        self.assertEqual(
            set(rendered),
            {"filen-mount.service", "filen-status.service", "filen-status.timer"},
        )
        for name, body in rendered.items():
            self.assertIn(MARKER, body, name)

        second = self.h.run("install")
        self.assertEqual(second.returncode, 0, second.stderr)
        again = {path.name: path.read_text(encoding="utf-8") for path in self.h.unit_dir.iterdir()}
        self.assertEqual(again, rendered)
        self.assertNotIn("curl", "\n".join(self.h.calls()))

    def test_install_refuses_foreign_unit(self):
        self.h.seed_binaries()
        self.h.unit_dir.mkdir(parents=True, exist_ok=True)
        foreign = self.h.unit_dir / "filen-mount.service"
        original = "# someone else's unit\n[Service]\n"
        foreign.write_text(original, encoding="utf-8")

        result = self.h.run("install")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr)
        self.assertEqual(foreign.read_text(encoding="utf-8"), original)

    def test_install_skips_download_when_version_marker_matches(self):
        self.h.seed_binaries()

        result = self.h.run("install")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("curl", "\n".join(self.h.calls()))
        self.assertEqual(
            (self.h.data_dir / "filen.version").read_text(encoding="utf-8").strip(),
            "0.2.8",
        )

    def test_install_redownloads_when_version_marker_differs(self):
        self.h.seed_binaries()
        (self.h.data_dir / "filen.version").write_text("0.2.0\n", encoding="utf-8")

        result = self.h.run("install")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("curl", "\n".join(self.h.calls()))

    def test_install_writes_default_settings(self):
        self.h.seed_binaries()

        result = self.h.run("install")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.h.settings_file.exists())

    def test_update_dispatches_install(self):
        self.h.seed_binaries()

        result = self.h.run("update")

        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("filen-mount.service", "filen-status.service", "filen-status.timer"):
            self.assertTrue((self.h.unit_dir / name).exists(), name)

    def test_repair_is_an_update_alias(self):
        self.h.seed_binaries()

        result = self.h.run("repair")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.h.unit_dir / "filen-mount.service").exists())

    # -------------------------------------------------------------- uninstall

    def test_uninstall_keeps_credential_by_default(self):
        self.h.seed_binaries()
        self.h.run("install")
        self.h.credential.parent.mkdir(parents=True, exist_ok=True)
        self.h.credential.write_text("blob", encoding="utf-8")

        result = self.h.run("uninstall")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.h.unit_dir.iterdir()), [])
        self.assertTrue(self.h.credential.exists())

    def test_uninstall_purge_removes_credential(self):
        self.h.seed_binaries()
        self.h.run("install")
        self.h.credential.parent.mkdir(parents=True, exist_ok=True)
        self.h.credential.write_text("blob", encoding="utf-8")

        result = self.h.run("uninstall", "--purge")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.h.unit_dir.iterdir()), [])
        self.assertFalse(self.h.credential.exists())

    def test_uninstall_flag_keeps_credential_by_default(self):
        self.h.seed_binaries()
        self.h.run("install")
        self.h.credential.parent.mkdir(parents=True, exist_ok=True)
        self.h.credential.write_text("blob", encoding="utf-8")

        result = self.h.run("--uninstall")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.h.unit_dir.iterdir()), [])
        self.assertTrue(self.h.credential.exists())

    def test_uninstall_flag_with_purge_removes_credential(self):
        self.h.seed_binaries()
        self.h.run("install")
        self.h.credential.parent.mkdir(parents=True, exist_ok=True)
        self.h.credential.write_text("blob", encoding="utf-8")

        result = self.h.run("--uninstall", "--purge")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.h.unit_dir.iterdir()), [])
        self.assertFalse(self.h.credential.exists())

    def test_uninstall_refuses_foreign_unit(self):
        self.h.unit_dir.mkdir(parents=True, exist_ok=True)
        foreign = self.h.unit_dir / "filen-mount.service"
        foreign.write_text("# someone else's unit\n", encoding="utf-8")

        result = self.h.run("uninstall")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr)
        self.assertTrue(foreign.exists())

    # -------------------------------------------------------- check / provision

    def test_check_reports_prerequisites(self):
        result = self.h.run("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok      fuse3", result.stdout)
        self.assertIn("ok      python3", result.stdout)
        self.assertIn("systemd 261", result.stdout)

    def test_provision_requires_a_terminal(self):
        self.h.seed_binaries()

        result = self.h.run("provision")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interactive", result.stderr)

    # -------------------------------------------------------- fragment producer

    def test_export_fragment_builds_contract(self):
        fake = write_exec(self.h.tmp / "filen-fake", FAKE_FILEN)
        out = self.h.runtime / "filen" / "api-status.json"

        result = self.h.run(
            "export-fragment",
            "--filen",
            str(fake),
            "--config-dir",
            str(self.h.runtime / "filen"),
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
        self.assertEqual(fragment["usedBytes"], 1000)
        self.assertEqual(fragment["quotaBytes"], 4000)
        self.assertIs(fragment["quotaKnown"], True)
        self.assertEqual(fragment["usagePercent"], 25.0)
        self.assertIsInstance(fragment["checkedAt"], int)
        self.assertEqual([item["name"] for item in fragment["files"]], ["one.txt", "two.txt"])
        self.assertEqual(fragment["files"][0]["folder"], "/a")
        self.assertEqual(fragment["files"][0]["modifiedTs"], 1767323045)
        self.assertEqual(fragment["files"][1]["sizeBytes"], 20)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_export_fragment_failure_writes_valid_json(self):
        fake = write_exec(
            self.h.tmp / "filen-fail",
            "#!/usr/bin/env bash\necho boom >&2\nexit 1\n",
        )
        out = self.h.tmp / "api-status.json"

        result = self.h.run(
            "export-fragment",
            "--filen",
            str(fake),
            "--config-dir",
            str(self.h.tmp),
            "--out",
            str(out),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        fragment = json.loads(out.read_text(encoding="utf-8"))
        self.assertIs(fragment["ok"], False)
        self.assertIn("error", fragment)
        self.assertIsInstance(fragment["checkedAt"], int)


if __name__ == "__main__":
    unittest.main()
