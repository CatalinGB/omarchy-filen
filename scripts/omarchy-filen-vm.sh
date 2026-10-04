#!/usr/bin/env bash
#
# scripts/omarchy-filen-vm.sh -- run the plugin's live/manual E2E on a fresh
# Omarchy in QEMU/KVM.
#
# The panel QML, live settings changes, logout/login autostart, offline and
# error-state checks cannot run headless, so they need a real (or virtual)
# Omarchy desktop. This helper automates the disposable-VM plumbing around that
# pass:
#
#   download   fetch + sha256-verify the official Omarchy ISO
#   base       create the base disk and boot the installer unattended (cidata)
#   run        boot a disposable overlay of the installed base (ssh on 2222)
#   ssh        log into the running guest
#   help       usage
#
# It never runs the E2E itself -- see docs/vm-testing.md and tests/e2e/live.sh.
#
# Everything is overridable through the environment (see usage below). The
# script is intentionally dependency-light: qemu, qemu-img, curl, and
# dosfstools + mtools (mkfs.vfat/mcopy) for the NoCloud seed drive.
#
set -euo pipefail

# ------------------------------------------------------------------ config

# The only place the Omarchy version is pinned. Change this one URL to move the
# whole toolchain to a new release; every other name is derived from it.
DEFAULT_OMARCHY_ISO="https://iso.omarchy.org/omarchy-4.0.4.iso"

OMARCHY_ISO="${OMARCHY_ISO:-$DEFAULT_OMARCHY_ISO}"
OMARCHY_VM_DIR="${OMARCHY_VM_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/omarchy-filen/vm}"
OMARCHY_CIDATA="${OMARCHY_CIDATA:-}"

VM_RAM="${VM_RAM:-8192}"   # guest RAM in MiB
VM_CPUS="${VM_CPUS:-4}"    # guest vCPUs
VM_DISK="${VM_DISK:-40G}"  # base disk size

# VRAM/renderer: VirGL is the accelerated path Hyprland wants; VM_GL=0 falls
# back to virtio-vga with software rendering (works, but slow).
VM_GL="${VM_GL:-1}"
VM_DISPLAY="${VM_DISPLAY:-}"
# VM_REUSE=1 keeps an existing run overlay instead of recreating it.
VM_REUSE="${VM_REUSE:-0}"

# Derived paths.
BASE_DISK="$OMARCHY_VM_DIR/base.qcow2"
RUN_DISK="$OMARCHY_VM_DIR/run.qcow2"
CIDATA_IMG="$OMARCHY_VM_DIR/cidata.img"
VARS_BASE="$OMARCHY_VM_DIR/base-vars.fd"
VARS_RUN="$OMARCHY_VM_DIR/run-vars.fd"
SSH_PORT=2222

# May be pre-set by the caller; detect_ovmf fills them when empty.
OVMF_CODE="${OVMF_CODE:-}"
OVMF_VARS="${OVMF_VARS:-}"

# Filled by configure_accel / configure_display before boot_vm runs.
ACCEL_ARGS=()
DISPLAY_ARGS=()

# ------------------------------------------------------------------ output

say() { printf '%s\n' "$*"; }
warn() { printf 'vm: warning: %s\n' "$*" >&2; }
die() {
  printf 'vm: error: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "required command not found: $c"
  done
}

usage() {
  cat <<EOF
$(basename -- "$0") -- fresh Omarchy in QEMU/KVM for the live E2E.

Usage: $(basename -- "$0") COMMAND

Commands:
  download   Fetch the Omarchy ISO and its .sha256 into OMARCHY_VM_DIR and
             verify the checksum with sha256sum -c.
  base       Create the base qcow2 and boot the ISO into the unattended
             install. Requires OMARCHY_CIDATA to point at a directory holding
             user_configuration.json, user_credentials.json and (optionally)
             authorized_keys. Install UNENCRYPTED so boots are hands-off.
  run        Boot a disposable overlay of the installed base, forwarding
             ssh to 127.0.0.1:${SSH_PORT}.
  ssh        ssh -p ${SSH_PORT} omarchy@127.0.0.1
  help       Show this message.

Environment:
  OMARCHY_VM_DIR  VM files                (default: \${XDG_DATA_HOME:-\$HOME/.local/share}/omarchy-filen/vm)
  OMARCHY_ISO     ISO URL or local path   (default: $DEFAULT_OMARCHY_ISO)
  OMARCHY_CIDATA  NoCloud seed directory  (required by 'base')
  VM_RAM          guest RAM in MiB        (default: $VM_RAM)
  VM_CPUS         guest vCPUs             (default: $VM_CPUS)
  VM_DISK         base disk size          (default: $VM_DISK)
  VM_GL           1 = VirGL, 0 = software (default: $VM_GL)
  VM_DISPLAY      QEMU -display value     (default: sdl,gl=on; VM_GL=0: none)
  VM_REUSE        1 = keep the run overlay (default: $VM_REUSE)
  OVMF_CODE,
  OVMF_VARS       firmware paths          (auto-detected)

See docs/vm-testing.md for the walkthrough and the manual checklist.
EOF
}

# ------------------------------------------------------------------ helpers

# iso_path -- echo the local path the ISO lives at (downloaded or user-given).
iso_path() {
  if [[ "$OMARCHY_ISO" == http* ]]; then
    printf '%s/%s\n' "$OMARCHY_VM_DIR" "$(basename -- "$OMARCHY_ISO")"
  else
    printf '%s\n' "$OMARCHY_ISO"
  fi
}

# verify_iso ISO -- check ISO against ISO.sha256 with sha256sum -c. The
# published checksum file may be a bare hash or 'HASH  FILENAME'; normalise it
# to the latter so sha256sum -c always works.
verify_iso() {
  local iso="$1"
  local sum="$iso.sha256"
  local expected check
  [[ -f "$sum" ]] || die "checksum file not found: $sum"
  expected="$(awk 'NF { print $1; exit }' "$sum")"
  if [[ ! "$expected" =~ ^[0-9a-fA-F]{64}$ ]]; then
    die "malformed checksum file (no sha256 found): $sum"
  fi
  check="$iso.sha256check"
  printf '%s  %s\n' "$expected" "$(basename -- "$iso")" > "$check"
  if ! ( cd "$(dirname -- "$iso")" && sha256sum -c "$(basename -- "$check")" ); then
    rm -f -- "$check"
    die "ISO checksum mismatch: $iso"
  fi
  rm -f -- "$check"
}

# detect_ovmf -- locate OVMF (edk2) firmware, honouring OVMF_CODE/OVMF_VARS.
# Uses the plain (non-secboot) code so Secure Boot stays off.
detect_ovmf() {
  if [[ -n "$OVMF_CODE" && -n "$OVMF_VARS" ]]; then
    [[ -f "$OVMF_CODE" ]] || die "OVMF_CODE not found: $OVMF_CODE"
    [[ -f "$OVMF_VARS" ]] || die "OVMF_VARS not found: $OVMF_VARS"
    return 0
  fi
  local dir pair code vars
  for dir in /usr/share/ovmf/x64 /usr/share/OVMF /usr/share/OVMF/x64 \
    /usr/share/edk2/x64 /usr/share/edk2/ovmf; do
    for pair in "OVMF_CODE.4m.fd:OVMF_VARS.4m.fd" \
      "OVMF_CODE_4M.fd:OVMF_VARS_4M.fd" \
      "OVMF_CODE.fd:OVMF_VARS.fd"; do
      code="${pair%%:*}"
      vars="${pair##*:}"
      if [[ -f "$dir/$code" && -f "$dir/$vars" ]]; then
        OVMF_CODE="$dir/$code"
        OVMF_VARS="$dir/$vars"
        return 0
      fi
    done
  done
  die "OVMF firmware not found. Install edk2-ovmf (Arch) or ovmf (Debian), or set OVMF_CODE and OVMF_VARS."
}

# configure_accel -- KVM when /dev/kvm is usable, TCG otherwise.
configure_accel() {
  if [[ -w /dev/kvm ]]; then
    ACCEL_ARGS=(-enable-kvm -cpu host)
  else
    warn "/dev/kvm missing or not writable; falling back to TCG software emulation (slow)."
    ACCEL_ARGS=(-cpu max)
  fi
}

# configure_display -- VirGL by default; software virtio-vga fallback.
configure_display() {
  if [[ "$VM_GL" == 1 ]]; then
    DISPLAY_ARGS=(-device virtio-vga-gl -display "${VM_DISPLAY:-sdl,gl=on}")
  else
    warn "VM_GL=0: using virtio-vga with software rendering (slow)."
    DISPLAY_ARGS=(-device virtio-vga -display "${VM_DISPLAY:-none}")
  fi
}

# fresh_vars DEST -- copy the writeable OVMF variable store for one boot.
fresh_vars() {
  cp -f -- "$OVMF_VARS" "$1"
}

# build_cidata DIR IMG -- pack DIR into a FAT image labelled 'cidata' (the
# cloud-init NoCloud volume the Omarchy installer reads).
build_cidata() {
  local dir="$1" img="$2" f
  rm -f -- "$img"
  qemu-img create -f raw "$img" 16M >/dev/null
  mkfs.vfat -n cidata "$img" >/dev/null
  for f in "$dir"/*; do
    [[ -f "$f" ]] || continue
    mcopy -o -i "$img" "$f" "::/"
  done
}

# boot_vm DISK VARS [extra qemu args...] -- the documented QEMU/KVM invocation.
boot_vm() {
  local disk="$1" vars="$2"
  shift 2
  qemu-system-x86_64 \
    -name "omarchy-filen-e2e" \
    -machine q35 \
    "${ACCEL_ARGS[@]}" \
    -smp "$VM_CPUS" \
    -m "$VM_RAM" \
    -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
    -drive if=pflash,format=raw,file="$vars" \
    -drive "file=$disk,if=virtio,format=qcow2" \
    "$@" \
    "${DISPLAY_ARGS[@]}" \
    -usb -device usb-tablet \
    -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
    -device virtio-net-pci,netdev=net0
}

# ------------------------------------------------------------------ commands

cmd_download() {
  need_cmd curl sha256sum
  mkdir -p "$OMARCHY_VM_DIR"
  local iso
  if [[ "$OMARCHY_ISO" == http* ]]; then
    iso="$(iso_path)"
    if [[ -f "$iso" ]]; then
      say "ISO already present: $iso"
    else
      say "Downloading $OMARCHY_ISO"
      curl -fL --progress-bar -o "$iso.part" "$OMARCHY_ISO"
      mv -f -- "$iso.part" "$iso"
    fi
    say "Downloading $OMARCHY_ISO.sha256"
    curl -fL --progress-bar -o "$iso.sha256" "$OMARCHY_ISO.sha256"
  else
    iso="$OMARCHY_ISO"
    [[ -f "$iso" ]] || die "ISO not found: $iso"
    say "Using local ISO: $iso"
  fi
  verify_iso "$iso"
  say "verified: $(basename -- "$iso")"
}

cmd_base() {
  need_cmd qemu-system-x86_64 qemu-img mkfs.vfat mcopy
  detect_ovmf
  configure_accel
  configure_display

  [[ -n "$OMARCHY_CIDATA" ]] ||
    die "OMARCHY_CIDATA is not set. Point it at a directory holding user_configuration.json, user_credentials.json and (optionally) authorized_keys; see docs/vm-testing.md."
  [[ -d "$OMARCHY_CIDATA" ]] || die "OMARCHY_CIDATA is not a directory: $OMARCHY_CIDATA"
  local f
  for f in user_configuration.json user_credentials.json; do
    [[ -f "$OMARCHY_CIDATA/$f" ]] || die "missing seed file: $OMARCHY_CIDATA/$f"
  done

  local iso
  iso="$(iso_path)"
  [[ -f "$iso" ]] || die "ISO not found: $iso (run '$0 download' first)"

  mkdir -p "$OMARCHY_VM_DIR"
  if [[ -f "$BASE_DISK" ]]; then
    say "Reusing existing base disk: $BASE_DISK"
  else
    say "Creating base disk ($VM_DISK): $BASE_DISK"
    qemu-img create -f qcow2 "$BASE_DISK" "$VM_DISK" >/dev/null
  fi

  say "Building cidata seed drive from: $OMARCHY_CIDATA"
  build_cidata "$OMARCHY_CIDATA" "$CIDATA_IMG"
  fresh_vars "$VARS_BASE"

  say "Booting the unattended installer. When it finishes, power the VM off."
  boot_vm "$BASE_DISK" "$VARS_BASE" \
    -boot "order=d" \
    -drive "file=$CIDATA_IMG,if=virtio,format=raw,readonly=on" \
    -drive "file=$iso,media=cdrom,if=ide,readonly=on"
}

cmd_run() {
  need_cmd qemu-system-x86_64 qemu-img
  detect_ovmf
  configure_accel
  configure_display

  [[ -f "$BASE_DISK" ]] || die "no base disk at $BASE_DISK (run '$0 base' first)"
  mkdir -p "$OMARCHY_VM_DIR"

  if [[ "$VM_REUSE" == 1 && -f "$RUN_DISK" ]]; then
    say "Reusing existing run overlay: $RUN_DISK"
  else
    rm -f -- "$RUN_DISK"
    say "Creating disposable overlay: $RUN_DISK"
    qemu-img create -f qcow2 -b "$BASE_DISK" -F qcow2 "$RUN_DISK" >/dev/null
  fi
  fresh_vars "$VARS_RUN"

  say "Booting Omarchy. SSH: ssh -p ${SSH_PORT} omarchy@127.0.0.1 (or '$0 ssh')."
  boot_vm "$RUN_DISK" "$VARS_RUN" -boot "order=c"
}

cmd_ssh() {
  need_cmd ssh
  exec ssh -p "$SSH_PORT" omarchy@127.0.0.1
}

# ------------------------------------------------------------------ dispatch

case "${1:-}" in
  download) cmd_download ;;
  base) cmd_base ;;
  run) cmd_run ;;
  ssh) cmd_ssh ;;
  help | -h | --help | "") usage ;;
  *)
    printf 'vm: unknown command: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac
