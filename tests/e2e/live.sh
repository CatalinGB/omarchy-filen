#!/usr/bin/env bash
#
# tests/e2e/live.sh -- live end-to-end pass for the filen.storage plugin.
#
# This is the layer CI cannot run: it drives the real `filen` binary, the real
# FUSE mount, the real systemd user units, and the real Filen API on an actual
# Omarchy machine. It automates every step it can and prompts exactly once --
# the interactive `setup provision` sign-in (email/password/2FA), which only a
# human can complete.
#
# Usage:
#   tests/e2e/live.sh
#
# Env overrides:
#   OMARCHY_FILEN_MOUNT_ROOT   mount root to check (default ~/Filen)
#   MOUNT_WAIT_SECONDS         how long to wait for the mount (default 90)
#   REPORT_DIR                 where to write the log (default .e2e-report)
#
# Exit status is 0 only when every step passed.
#
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SETUP="$REPO_ROOT/bin/setup"
STATUS="$REPO_ROOT/bin/status"
MOUNT_ROOT="${OMARCHY_FILEN_MOUNT_ROOT:-$HOME/Filen}"
MOUNT_UNIT="omarchy-filen-mount.service"
MOUNT_WAIT_SECONDS="${MOUNT_WAIT_SECONDS:-90}"
CREDENTIAL="$HOME/.config/credstore.encrypted/filen-auth"

REPORT_DIR="${REPORT_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-filen/e2e}"
mkdir -p "$REPORT_DIR"
LOG="$REPORT_DIR/live-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() { printf '  PASS  %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { printf '  FAIL  %s\n' "$1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
skip() { printf '  SKIP  %s\n' "$1"; SKIP_COUNT=$((SKIP_COUNT + 1)); }
step() { printf '\n== %s ==\n' "$1"; }

# ------------------------------------------------------------------- steps

step_validate() {
  step "Validate plugin (omarchy plugin validate)"
  if ! command -v omarchy >/dev/null 2>&1; then
    skip "omarchy is not on PATH (run on a real Omarchy box)"
    return 0
  fi
  if omarchy plugin validate "$REPO_ROOT"; then
    pass "manifest valid"
  else
    fail "manifest invalid"
  fi
}

step_install() {
  step "Install (setup install)"
  local out
  if out="$("$SETUP" install 2>&1)"; then
    printf '%s\n' "$out"
    pass "setup install"
  else
    printf '%s\n' "$out"
    fail "setup install"
  fi
}

step_provision() {
  step "Provision (interactive; the one human step)"
  if [[ -e "$CREDENTIAL" ]]; then
    pass "credential already present (skipping sign-in)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    fail "no TTY: re-run from a terminal and complete the Filen sign-in"
    return 0
  fi
  printf '>>> Complete the Filen sign-in (email/password/2FA) when prompted.\n'
  read -r -p ">>> Press Enter to continue..." _ || true
  if "$SETUP" provision; then
    pass "credential stored and mount started"
  else
    fail "provision"
  fi
}

wait_for_mount() {
  local waited=0
  while (( waited < MOUNT_WAIT_SECONDS )); do
    if mountpoint -q "$MOUNT_ROOT" 2>/dev/null; then
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  return 1
}

step_wait_mount() {
  step "Wait for the mount at $MOUNT_ROOT"
  if wait_for_mount; then
    pass "mounted"
  else
    fail "mount did not appear within ${MOUNT_WAIT_SECONDS}s"
  fi
}

step_status() {
  step "Status contract (bin/status)"
  local json
  if ! json="$("$STATUS" 2>&1)"; then
    fail "status helper exited non-zero"
    return 0
  fi
  printf '%s\n' "$json"
  if printf '%s' "$json" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("ok") else 1)' 2>/dev/null; then
    pass "status JSON valid and ok=true"
  else
    fail "status JSON invalid or ok=false"
  fi
}

step_systemctl_toggle() {
  step "Unmount / mount via systemctl --user"
  if systemctl --user stop "$MOUNT_UNIT" && ! mountpoint -q "$MOUNT_ROOT" 2>/dev/null; then
    pass "stop unmounted"
  else
    fail "stop did not unmount"
  fi

  if systemctl --user start "$MOUNT_UNIT"; then
    if wait_for_mount; then
      pass "start remounted"
    else
      fail "start did not remount within ${MOUNT_WAIT_SECONDS}s"
    fi
  else
    fail "start failed"
  fi
}

step_doctor() {
  step "Doctor (setup doctor)"
  if "$SETUP" doctor; then
    pass "doctor healthy"
  else
    fail "doctor unhealthy"
  fi
}

step_roundtrip() {
  step "File round-trip in $MOUNT_ROOT"
  local probe="$MOUNT_ROOT/.omarchy-filen-e2e-$$"
  local payload
  payload="e2e-$$-$(date +%s)"
  if ! printf '%s\n' "$payload" > "$probe" 2>/dev/null; then
    fail "write to the mount failed"
    return 0
  fi
  # Give the managed rclone a moment to flush through to the provider.
  sleep 3
  local got=""
  got="$(cat "$probe" 2>/dev/null || true)"
  if [[ "$got" == "$payload" ]]; then
    pass "read-back matches"
  else
    fail "read-back mismatch"
  fi
  rm -f "$probe" 2>/dev/null || true
}

step_uninstall_reinstall() {
  step "Uninstall / reinstall"
  if "$SETUP" uninstall; then
    pass "uninstall"
  else
    fail "uninstall"
  fi

  if "$SETUP" install; then
    pass "reinstall"
  else
    fail "reinstall"
    return 0
  fi

  if systemctl --user start "$MOUNT_UNIT"; then
    if wait_for_mount; then
      pass "remounted after reinstall"
    else
      fail "did not remount after reinstall"
    fi
  else
    fail "could not start the unit after reinstall"
  fi
}

# ------------------------------------------------------------------- main

main() {
  printf 'filen.storage live E2E\n'
  printf 'report log: %s\n' "$LOG"

  step_validate || true
  step_install || true
  step_provision || true
  step_wait_mount || true
  step_status || true
  step_systemctl_toggle || true
  step_doctor || true
  step_roundtrip || true
  step_uninstall_reinstall || true

  printf '\n===== SUMMARY =====\n'
  printf 'passed: %d  failed: %d  skipped: %d\n' "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT"
  if (( FAIL_COUNT == 0 )); then
    printf 'RESULT: PASS\n'
    return 0
  fi
  printf 'RESULT: FAIL\n'
  return 1
}

main "$@"
