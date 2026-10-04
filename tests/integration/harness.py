#!/usr/bin/env python3
"""Hermetic integration harness for the filen.storage plugin (H13).

Builds a throwaway ``HOME``/``XDG_*`` tree, drops fake ``systemctl``,
``systemd-creds``, ``curl``, ``mountpoint``, ``fusermount3`` and ``filen``
executables on ``PATH``, and drives the *real* ``bin/setup`` and ``bin/status``
scripts against them. No root, no network, no real systemd, no real FUSE.

The fakes are deliberately small: each one records what it was asked to do (so
tests can assert call sequences) and reads its "live state" from files under
``<tmp>/fake-state`` so a test can flip the mount unit between
active/inactive/failed and enabled/disabled.
"""

import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETUP = REPO / "bin" / "setup"
STATUS = REPO / "bin" / "status"

MARKER = "# Managed by the filen.storage Omarchy plugin; do not edit."
FILEN_VERSION = "0.2.9"

# ------------------------------------------------------------------ fakes

FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
echo "systemctl $*" >> "$SYSTEMCTL_LOG"
args=("$@")
if [[ "${args[0]:-}" == "--user" ]]; then args=("${args[@]:1}"); fi
cmd="${args[0]:-}"
show_value() {
  local state="inactive"
  if [[ -n "${FAKE_SYSTEMCTL_STATE:-}" && -f "$FAKE_SYSTEMCTL_STATE" ]]; then
    state="$(cat "$FAKE_SYSTEMCTL_STATE")"
  fi
  if [[ " $* " == *" --value "* ]]; then
    printf '%s\n' "$state"
  else
    printf 'ActiveState=%s\n' "$state"
  fi
}
case "$cmd" in
  show)       show_value "${args[@]:1}" ;;
  is-enabled)
    enabled="disabled"
    if [[ -n "${FAKE_SYSTEMCTL_ENABLED:-}" && -f "$FAKE_SYSTEMCTL_ENABLED" ]]; then
      enabled="$(cat "$FAKE_SYSTEMCTL_ENABLED")"
    fi
    printf '%s\n' "$enabled"
    [[ "$enabled" == "enabled" ]] && exit 0 || exit 1 ;;
  *) exit 0 ;;
esac
"""

FAKE_SYSTEMD_CREDS = r"""#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
  echo "systemd 261 (261.1)"
  exit 0
fi
if [[ "${1:-}" == "encrypt" ]]; then
  input="${@: -2:1}"
  output="${@: -1}"
  if [[ -n "${SYSTEMD_CREDS_RECORD:-}" && -f "$input" ]]; then
    cp "$input" "$SYSTEMD_CREDS_RECORD"
  fi
  printf 'ENCRYPTED-BLOB\n' > "$output"
  exit 0
fi
exit 0
"""

FAKE_CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$SYSTEMCTL_LOG"
out=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[i]}" == "-o" ]]; then out="${args[i+1]:-}"; fi
done
if [[ -n "$out" ]]; then
  printf '#!/usr/bin/env bash\nexit 0\n' > "$out"
fi
exit 0
"""

FAKE_MOUNTPOINT = r"""#!/usr/bin/env bash
# Report the configured mount root as present; the fake systemd user manager
# "started" the unit, and there is no real FUSE in a hermetic test.
exit 0
"""

FAKE_FUSERMOUNT = "#!/usr/bin/env bash\nexit 0\n"

# The generic PATH `filen`. It supports the provision export and the JSON
# fragment producer so it can stand in for either flow when copied to the
# plugin data dir by seed_filen().
FAKE_FILEN = r"""#!/usr/bin/env bash
if [[ -n "${FILEN_ARGV_LOG:-}" ]]; then printf '%s\n' "$0 $*" >> "$FILEN_ARGV_LOG"; fi
cfg=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [[ "${args[i]}" == "--config-dir" ]]; then cfg="${args[i+1]:-}"; fi
done
case "$*" in
  *export-auth-config*)
    [[ -n "$cfg" ]] || cfg="."
    mkdir -p "$cfg"
    printf '%s\n' "${FILEN_FAKE_CANARY:-CANARY-default}" \
      > "${cfg}/filen-cli-auth-config.txt"
    exit 0 ;;
  *"stat /a/one.txt"*)
    echo '{"name":"one.txt","type":"file","size":10,"modified":"2026-01-02T03:04:05Z","created":null,"uuid":"u1"}' ;;
  *"stat /a/two.txt"*)
    echo '{"name":"two.txt","type":"file","size":20,"modified":1700000000,"created":null,"uuid":"u2"}' ;;
  *"list-recents"*)
    echo '{"directories":["/a"],"files":["/a/one.txt","/a/two.txt"]}' ;;
  *"stat /"*)
    echo '{"type":"drive","usedStorage":1000,"totalStorage":4000,"files":3,"directories":1}' ;;
  *) exit 0 ;;
esac
"""


def write_exec(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


class Harness:
    """A hermetic install of the plugin under a temporary filesystem tree."""

    def __init__(self, root):
        self.tmp = Path(root)
        self.home = self.tmp / "home"
        self.config = self.tmp / "config"
        self.data = self.tmp / "data"
        self.runtime = self.tmp / "run"
        self.fake_bin = self.tmp / "fake-bin"
        self.fake_state = self.tmp / "fake-state"
        self.tmpdir = self.tmp / "tmp"  # TMPDIR for provision's mktemp -d
        for directory in (
            self.home,
            self.config,
            self.data,
            self.runtime,
            self.fake_bin,
            self.fake_state,
            self.tmpdir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.exec_log = self.tmp / "systemctl.log"
        self.argv_log = self.fake_state / "filen-argv"
        self.creds_record = self.fake_state / "creds-input"
        self.mount_root = self.home / "Filen"

        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("OMARCHY_FILEN_"):
                del self.env[key]
        self.env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.config),
                "XDG_DATA_HOME": str(self.data),
                "XDG_RUNTIME_DIR": str(self.runtime),
                "TMPDIR": str(self.tmpdir),
                "PATH": f"{self.fake_bin}{os.pathsep}{self.env.get('PATH', '')}",
                "SYSTEMCTL_LOG": str(self.exec_log),
                "FAKE_SYSTEMCTL_STATE": str(self.fake_state / "active-state"),
                "FAKE_SYSTEMCTL_ENABLED": str(self.fake_state / "enabled"),
                "SYSTEMD_CREDS_RECORD": str(self.creds_record),
                "FILEN_ARGV_LOG": str(self.argv_log),
            }
        )
        self._install_fakes()

    # ------------------------------------------------------------- locations

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
    def rclone_dir(self):
        return self.data_dir / "rclone"

    @property
    def credential(self):
        return self.config / "credstore.encrypted" / "filen-auth"

    @property
    def settings_file(self):
        return self.config / "omarchy-filen" / "settings.conf"

    @property
    def runtime_filen(self):
        return self.runtime / "filen"

    @property
    def api_fragment(self):
        return self.runtime_filen / "api-status.json"

    # ----------------------------------------------------------------- fakes

    def _install_fakes(self):
        write_exec(self.fake_bin / "systemctl", FAKE_SYSTEMCTL)
        write_exec(self.fake_bin / "systemd-creds", FAKE_SYSTEMD_CREDS)
        write_exec(self.fake_bin / "curl", FAKE_CURL)
        write_exec(self.fake_bin / "mountpoint", FAKE_MOUNTPOINT)
        write_exec(self.fake_bin / "fusermount3", FAKE_FUSERMOUNT)
        write_exec(self.fake_bin / "filen", FAKE_FILEN)

    # -------------------------------------------------------------- fixtures

    def seed_rclone(self):
        """Pre-seed the managed rclone the way a real install would.

        The pinned rclone checksum cannot be forged offline, so tests place the
        already-verified binary where ``seed_rclone`` looks for it and let
        install skip the download.
        """
        target = self.run("rclone-target").stdout.strip()
        write_exec(self.rclone_dir / target, "#!/usr/bin/env bash\nexit 0\n")
        return target

    def seed_filen(self, version=FILEN_VERSION):
        """Place an already-downloaded filen binary + version marker."""
        write_exec(self.filen_bin, FAKE_FILEN)
        (self.data_dir / "filen.version").write_text(
            version + "\n", encoding="utf-8"
        )

    def seed_all(self, version=FILEN_VERSION):
        self.seed_rclone()
        self.seed_filen(version=version)

    def set_unit_state(self, state):
        (self.fake_state / "active-state").write_text(
            state + "\n", encoding="utf-8"
        )

    def set_unit_enabled(self, enabled=True):
        (self.fake_state / "enabled").write_text(
            ("enabled" if enabled else "disabled") + "\n", encoding="utf-8"
        )

    def write_credential(self, blob="ENCRYPTED-BLOB\n"):
        self.credential.parent.mkdir(parents=True, exist_ok=True)
        self.credential.write_text(blob, encoding="utf-8")

    # --------------------------------------------------------------- running

    def run(self, *args, env=None, timeout=60):
        return subprocess.run(
            [str(SETUP), *args],
            capture_output=True,
            text=True,
            env=env or self.env,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=str(self.tmp),
        )

    def run_status(self, *extra, timeout=30):
        args = [
            str(STATUS),
            "--mount-root",
            str(self.mount_root),
            "--filen-bin",
            str(self.filen_bin),
            "--credential",
            str(self.credential),
            "--runtime-dir",
            str(self.runtime_filen),
            *extra,
        ]
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=str(self.tmp),
        )

    def run_pty(self, *args, timeout=60):
        """Run a setup subcommand under a pty so ``[[ -t 0 ]]`` succeeds.

        Provisioning refuses a non-TTY, so this is the only way to exercise
        ``setup provision`` end to end.
        """
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(
                [str(SETUP), *args],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=self.env,
                cwd=str(self.tmp),
                close_fds=True,
            )
        finally:
            os.close(slave)

        chunks = []
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                proc.kill()
                break
            ready, _, _ = select.select([master], [], [], remaining)
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait()
        os.close(master)
        output = b"".join(chunks).decode("utf-8", "replace")
        return subprocess.CompletedProcess(
            [str(SETUP), *args], proc.returncode, output, output
        )

    # -------------------------------------------------------------- queries

    def calls(self):
        if not self.exec_log.exists():
            return []
        return self.exec_log.read_text(encoding="utf-8").splitlines()

    def argv_calls(self):
        if not self.argv_log.exists():
            return []
        return self.argv_log.read_text(encoding="utf-8").splitlines()

    def units(self):
        if not self.unit_dir.exists():
            return {}
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(self.unit_dir.iterdir())
            if path.is_file()
        }


if __name__ == "__main__":  # pragma: no cover - manual poke
    with __import__("tempfile").TemporaryDirectory() as root:
        harness = Harness(root)
        print(harness.run("check").stdout)
        sys.exit(0)
