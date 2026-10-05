---
name: filen
description: The Filen end-to-end-encrypted cloud drive mounted in the Omarchy bar through the io.github.catalingb.filen plugin — check mount status and storage, open the panel or its settings window, mount or unmount, and read the recent-files feed. Use when the user asks about their Filen drive, its mount status or quota, or wants to mount, unmount, or configure it.
---

# Filen (Omarchy plugin)

`io.github.catalingb.filen` mounts a Filen account as a FUSE mount under a
systemd **user** service and surfaces it in the Omarchy bar. This is a **mount,
not a sync client**: there is no offline copy, it is a single account, and the
pinned `filen-rs` CLI is a pre-release. The credential is held only by the
units, never by the panel or the bar.

## State

The bar icon shows one worst-first state: `not-installed`, `needs-auth`,
`stopped`, `mounting`, `mounted`, `failed`. The panel's **Status** row is
authoritative; the raw systemd unit state is an internal detail, not user-facing.

## Drive it from the shell (IPC)

The panel exposes an IPC route under the plugin id:

```bash
omarchy-shell io.github.catalingb.filen status    # the status line, e.g. "Mounted"
omarchy-shell io.github.catalingb.filen open      # open the panel
omarchy-shell io.github.catalingb.filen toggle    # open/close the panel
omarchy-shell io.github.catalingb.filen settings  # open/close the settings window
omarchy-shell io.github.catalingb.filen refresh   # re-poll local status
```

`bin/status` prints the same non-secret JSON the panel consumes and never runs
`filen` or touches the credential. The contract is in
[`docs/status-contract.md`](../../docs/status-contract.md).

## Setup, update, repair (interactive — a terminal, not an agent)

First-run and maintenance are a terminal flow:

```bash
"$PLUGIN/bin/setup" install     # download the pinned filen + rclone seed, write units
"$PLUGIN/bin/setup" provision   # sign in (email/password/2FA), encrypt the credential
"$PLUGIN/bin/setup" doctor      # pinned vs installed, units, credential, mount state
"$PLUGIN/bin/setup" settings MOUNT_ROOT=~/Filen CACHE_SIZE=4G API_REFRESH_MIN=10
```

The credential is a systemd-encrypted blob at
`~/.config/credstore.encrypted/filen-auth` and the plaintext is shredded. Never
ask a user to paste it.

## Settings

Editable from the panel cogwheel (a separate window) or by editing the plugin's
entry in `~/.config/omarchy/shell.json`: mount folder, cache limit, status and
storage refresh cadences, show-in-bar, show-recent-files, mount-at-login, and
Reset to defaults. The service mirrors the mount-affecting keys to
`~/.config/omarchy-filen/settings.conf` for the units.

## When something is wrong

- **needs-auth** — re-run `setup provision`.
- **failed** — the unit log:
  `journalctl --user -u omarchy-filen-mount.service`.
- **offline** — the panel keeps the last state and ages `checkedAt`; it is not
  `failed`.
- The full state → cause → action matrix is in
  [`docs/troubleshooting.md`](../../docs/troubleshooting.md).
