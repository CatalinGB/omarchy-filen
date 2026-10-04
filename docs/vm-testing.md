# VM testing — the live E2E on a fresh Omarchy

The live/manual end-to-end pass for `io.github.catalingb.filen` only means
something on a real Omarchy desktop with a real Filen account: it exercises QML,
FUSE, systemd, and the Filen API together, which CI cannot do. This guide
reproduces that pass in a **disposable QEMU/KVM virtual machine** so you do not
need a spare laptop and can start from a genuinely clean Omarchy every time.

It pairs with [verification.md](verification.md) (the checklist) and
[tests/e2e/live.sh](../tests/e2e/live.sh) (the automated part). The plumbing is
wrapped by [scripts/omarchy-filen-vm.sh](../scripts/omarchy-filen-vm.sh).

## Why a VM

Layer 1 of [verification.md](verification.md) runs in CI, but the parts that
matter most here cannot:

- The panel/bar are QML loaded by the Omarchy shell and import the in-shell
  `qs.*` modules, so they **cannot be compiled or driven headlessly**
  (verification.md, *Notes*).
- **Live settings changes** (mount folder / cache limit rewrite
  `settings.conf` and restart the mount), **logout/login autostart** (H06),
  **offline behaviour** (H08), **panel error states** (H10), and
  **multi-monitor agreement** (H11) need a graphical session, a human, and a
  reboot respectively.
- `tests/e2e/live.sh` automates the deterministic steps and prompts **exactly
  once** for the interactive Filen sign-in (email/password/2FA), which only a
  person can complete.

A VM gives that session a clean, reproducible, throwaway home without a second
machine — including the ability to reboot or corrupt state freely.

## Get and verify the ISO

There is **no generic Linux VM image** for Omarchy. `omacom/try-omarchy` targets
Apple Silicon and Windows hosts only, so on Linux **the ISO is the way in**.

Download the official `omarchy-4.0.4.iso` from <https://iso.omarchy.org/> along
with its `.sha256` and `.sig`:

```bash
cd ~/Downloads
base=https://iso.omarchy.org/omarchy-4.0.4.iso
curl -fsSLO "$base"
curl -fsSLO "$base.sha256"
curl -fsSLO "$base.sig"

# 1. Checksum:
sha256sum -c omarchy-4.0.4.iso.sha256

# 2. Signature — the release key fingerprint must be
#    40DFB630FF42BCFFB047046CF0134EE680CAC571
gpg --recv-keys 40DFB630FF42BCFFB047046CF0134EE680CAC571
gpg --verify omarchy-4.0.4.iso.sig omarchy-4.0.4.iso
```

The helper does the download + `sha256sum -c` half for you:

```bash
scripts/omarchy-filen-vm.sh download
```

It stores the ISO and its `.sha256` under `$OMARCHY_VM_DIR` (default
`~/.local/share/omarchy-filen/vm`) and refuses to continue on a mismatch. Point
`OMARCHY_ISO` at an already-downloaded local path to have it verify that copy
instead.

## One-time unattended base install

Omarchy's installer is driven by a **cloud-init NoCloud `cidata` volume**: a
small FAT drive whose label is `cidata`, attached as a second disk. The
installer reads three files from its root:

| File | Contents |
|---|---|
| `user_configuration.json` | archinstall config: target disk, hostname, timezone, keyboard, bootloader, user. |
| `user_credentials.json` | the `omarchy` user's password (and any other accounts). |
| `authorized_keys` | **optional** — SSH public key(s) for hands-off login. |

Two rules make the base boot non-interactively:

1. **Install unencrypted.** A LUKS passphrase would have to be typed at every
   boot, which defeats the whole point. The VM is disposable and holds only a
   test Filen credential, so full-disk encryption adds nothing here.
2. Keep `authorized_keys` present so `scripts/omarchy-filen-vm.sh ssh` works
   without a password.

The exact JSON schema evolves with archinstall, so treat the files as
*contents*, not boilerplate: the canonical generator is
`omarchy-iso/test/integration.d/base-test.sh` upstream, and the Omarchy manual
chapter *Unattended installs* (`manual/51-unattended-installs.md`) documents the
supported fields. A minimal `user_configuration.json` needs at least the disk
layout (unencrypted), hostname, timezone, and keyboard; `user_credentials.json`
needs the `omarchy` user and password; `authorized_keys` is one public key per
line.

Then build the base:

```bash
OMARCHY_CIDATA=~/omarchy-vm/cidata scripts/omarchy-filen-vm.sh base
```

The script creates `base.qcow2` (default 40 GB), packs the `cidata` directory
into a labelled FAT image, and boots the ISO into the unattended install with a
graphical console so you can watch it finish. **Power the VM off when it is
done** — the installed disk is now the reusable base. `base` refuses to run
without `OMARCHY_CIDATA`, and names the missing file if the directory is
incomplete.

## Disposable per-run overlay

Never boot the base directly. Each run gets a **copy-on-write overlay** plus a
fresh writeable OVMF variable store, so anything the run does — clone the
plugin, store a credential, corrupt a unit — is discarded when the overlay is
recreated:

```bash
qemu-img create -f qcow2 -b base.qcow2 -F qcow2 run.qcow2
cp /usr/share/ovmf/x64/OVMF_VARS.4m.fd run-vars.fd
```

`scripts/omarchy-filen-vm.sh run` does exactly this (and refuses if `base.qcow2`
is missing). Set `VM_REUSE=1` to keep the current overlay across boots — useful
when a single run needs a reboot to check H06 — otherwise the next `run` starts
from a pristine base again.

## The QEMU/KVM invocation

The documented command, with each flag explained:

```bash
qemu-system-x86_64 \
  -name omarchy-filen-e2e \
  -machine q35 -enable-kvm -cpu host \
  -smp 4 -m 8192 \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/ovmf/x64/OVMF_CODE.4m.fd \
  -drive if=pflash,format=raw,file=run-vars.fd \
  -drive file=run.qcow2,if=virtio,format=qcow2 \
  -device virtio-vga-gl -display sdl,gl=on \
  -usb -device usb-tablet \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22 \
  -device virtio-net-pci,netdev=net0
```

- **OVMF (Secure Boot off).** `OVMF_CODE.4m.fd` is the plain edk2 code; a fresh
  copy of `OVMF_VARS.4m.fd` is the per-run variable store. No secboot build is
  used.
- **`-machine q35 -enable-kvm -cpu host`.** Modern chipset and hardware
  acceleration. `-cpu host` is only valid with KVM; the helper drops it and
  warns when `/dev/kvm` is unavailable.
- **`virtio-vga-gl` + `-display sdl,gl=on`.** VirGL gives Hyprland an EGL
  renderer under Wayland. On a host without usable GL, fall back to
  `-device virtio-vga -display none` (software rendering; slow, but functional
  for checks that do not need the panel).
- **`-m 8192`, 40 GB disk on `virtio-blk-pci`.** The research's sizing; the
  overlay chain keeps the host cost bounded.
- **ISO on `ide-cd`** (base install only) and **`-boot order=d`** so the
  installer is booted ahead of the empty disk.
- **`hostfwd=tcp:127.0.0.1:2222-:22`** forwards host port 2222 to the guest's
  SSH, which is how the E2E is driven without the console.

`scripts/omarchy-filen-vm.sh base` runs this with the extra `cidata` FAT drive
and ISO attached; `run` runs it against the overlay alone (`-boot order=c`).

## Running the E2E

Once the base exists:

```bash
# 1. Boot a disposable overlay of the installed base.
scripts/omarchy-filen-vm.sh run

# 2. In another terminal, log in (ssh key from authorized_keys).
scripts/omarchy-filen-vm.sh ssh
```

In the guest, clone the plugin and run the automated pass:

```bash
sudo pacman -S --needed --noconfirm git
git clone https://github.com/CatalinGB/omarchy-filen.git
cd omarchy-filen
tests/e2e/live.sh
```

`live.sh` runs plugin validate → `setup install` → `setup provision` → wait for
the mount → `bin/status` contract → systemctl stop/start → `setup doctor` →
file round-trip → uninstall/reinstall, printing `PASS`/`FAIL`/`SKIP` per step.
It prompts once for the **interactive Filen sign-in** (email/password/2FA),
which needs a terminal — run it from the VM console or over `ssh -t`; a
non-TTY run fails that step by design.

Then work the manual items the script cannot cover, straight from
[verification.md](verification.md):

- **H06 — mount at login.** Log out and back in (or rebuild a disposable run and
  log in); confirm `~/Filen` is mounted and the panel shows **Mounted** with no
  manual action, via `graphical-session.target`.
- **H08 — offline.** Drop the guest network; confirm the unit does not storm,
  quota shows stale (`quotaKnown:false`, aging `checkedAt`), and cached files
  still read. Restore the network; confirm recovery without manual action.
- **H10 — panel error states.** Reproduce **not-installed**, **needs-auth**, and
  **failed** (remove the credential / stop the unit / corrupt the unit); each
  must show only the correct action. Screenshot each.
- **H11 — multi-monitor.** Attach a second virtual display; confirm one service
  instance polls once and both bar widgets agree.

Record the `live.sh` log (default
`~/.local/state/omarchy-filen/e2e/`) and the screenshots with the checklist
results — that evidence is what closes the TODO items.

## Caveats

- **Encryption blocks hands-off boot.** Install the base unencrypted, or every
  start stalls on a LUKS prompt at the console.
- **VirGL vs software rendering.** `virtio-vga-gl`/`gl=on` is the accelerated
  path; the `virtio-vga -display none` fallback works but is slow and gives no
  graphical console. Keep the accelerated display (SDL/SPICE/VNC) when testing
  the panel or logout/login.
- **The graphical console is required** for panel interactions and the
  logout/login step; `-display none` is SSH-only.
- **The overlay is disposable.** Without `VM_REUSE=1`, every `run` starts fresh
  from the base, so re-clone and re-provision each time.
- **SSH host key changes per run** (fresh overlay). Clear the stale entry with
  `ssh-keygen -R '[127.0.0.1]:2222'` if SSH refuses the connection.

## See also

- [verification.md](verification.md) — the three verification layers and the
  manual checklist this guide runs.
- [tests/e2e/live.sh](../tests/e2e/live.sh) — the automated live pass.
- [scripts/omarchy-filen-vm.sh](../scripts/omarchy-filen-vm.sh) — the helper
  documented here.
- [supported-environments.md](supported-environments.md) — what Omarchy and
  systemd versions the plugin requires.
