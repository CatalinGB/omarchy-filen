# Supported environments

What `filen.storage` runs on, what it needs, and what it does not promise.

## Platform

| Component | Supported | Notes |
|---|---|---|
| **Omarchy** | **4+** (the Quattro shell plugin system) | The bar widget and panel are QML loaded by the Omarchy shell; the plugin also uses `omarchy plugin add/validate/update`. Earlier Omarchy releases do not have the plugin kind system this builds on. |
| **Linux** | x86_64 / aarch64 | The plugin is developed and smoke-tested on Omarchy (Arch-based). Other systemd distros should work but are untested. |
| **systemd** | **≥ 256** (hard requirement) | `systemd-creds encrypt --user` (the credential design) needs 256. `LoadCredential=`/`LoadCredentialEncrypted=` in user units needs 250. Omarchy currently ships 261. On older systemd the credential mechanism is unavailable and the design does not work — see [SECURITY.md](../SECURITY.md). |
| **libc** | gnu **or** musl | The pinned `filen` asset is chosen for the running libc (`-unknown-linux-gnu` / `-musl`). Detection is automatic. |

## Required tools

The plugin detects each of these and offers an install action; nothing is
installed by hand. `bin/setup check` reports the same set.

| Tool | Why | Source |
|---|---|---|
| `fuse3` / `fusermount3` | The FUSE mount is how `~/Filen` appears | Omarchy ships it |
| `python3` | The credential-free `bin/status` helper | Omarchy ships it |
| `curl` | Downloading the pinned `filen` and rclone | Omarchy ships it |
| `systemd` / `systemctl` / `journalctl` | Units, timers, and logs | Omarchy ships it |
| `systemd-creds` | Encrypting the credential blob at rest | systemd ≥ 256 |

## Architectures

| Arch | `filen` asset | rclone target |
|---|---|---|
| x86_64 | `filen-cli-<ver>-x86_64-unknown-linux-<libc>` | `rclone-v1.74.2-linux-amd64` |
| aarch64 | `filen-cli-<ver>-aarch64-unknown-linux-<libc>` | `rclone-v1.74.2-linux-arm64` |

Any other `uname -m` is rejected by `bin/setup` with
`unsupported architecture`.

## Pinned versions

The plugin pins both runtimes and updates them deliberately (see
[pin maintenance](pin-maintenance.md)):

| Runtime | Pinned | Why this version |
|---|---|---|
| **`filen` CLI** (`filen-rs`) | **0.2.9** | 0.2.8 panics on `filen mount` (`pipe_output_to_logs`, `Option::unwrap()` on `None`). 0.2.9 fixes it but is published as a **GitHub pre-release**. See the [upstream issue draft](upstream-filen-rs-0.2.8-mount-panic.md). |
| **rclone** | **1.74.2** | The version `filen-rs` downloads itself; the plugin pre-seeds the same checksum-verified build so it is not re-downloaded on every start. |

The versions live in `bin/setup` (`FILEN_VERSION`, `RCLONE_VERSION`) and are
reported by `setup doctor`.

## The beta caveat

`filen-rs` — the `filen` CLI this plugin is built on — is a **public beta**:
*"Some functionality might still be missing, and there might be bugs."* The
plugin mitigates this by pinning a known-good version and updating it only after
the integration suite and a live smoke mount pass. It cannot remove the beta
risk, and it can only integrate the capabilities the CLI exposes. The specific
limitations that follow from that are listed at the end of
[troubleshooting.md](troubleshooting.md#known-limitations).

## What is intentionally not supported

- **A sync client.** Filen appears as a mount, not a synced folder. There is no
  offline copy and no two-way background sync. See
  [Known limitations](troubleshooting.md#known-limitations).
- **Non-Omarchy desktops.** The plugin is an Omarchy shell plugin; the panel and
  bar widget are not portable to other shells as-is.
- **Older systemd.** Without `systemd-creds --user` there is no supported
  credential mechanism here.
