# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-04

### Added

- An Omarchy shell plugin (`filen.storage`) with a bar widget and panel for
  Filen mount status, storage quota, and recent files.
- Two-step panel setup: **Install Filen** (pinned `filen` binary, rclone, and
  systemd units) then **Set up Filen** (sign in and store the credential).
- A systemd-supervised FUSE mount (`omarchy-filen-mount.service`) plus a credentialed
  `filen-status.{timer,service}` producer; the panel stays credential-free.
- A machine-bound **systemd credential** at
  `~/.config/credstore.encrypted/filen-auth`; plaintext is shredded and keys
  never persist outside tmpfs.
- Mount / Unmount and Mount-at-login controls, and recent files that open in
  Nautilus.
- Live **Mount folder** and **Cache size limit** settings, written to
  `~/.config/omarchy-filen/settings.conf` and applied by restarting the mount.
- `bin/setup` (`install`, `provision`, `update`, `uninstall`) and the
  credential-free `bin/status` helper.
- Docs: the [status contract](docs/status-contract.md),
  [prerequisites](docs/prerequisites.md), and [security model](SECURITY.md).

### Fixed

- Setup now describes the real two-step Install → Set up flow, and states that
  the drive mounts at login after Set up.
- Install instructions point at the canonical repository
  (`https://github.com/CatalinGB/omarchy-filen.git`).
