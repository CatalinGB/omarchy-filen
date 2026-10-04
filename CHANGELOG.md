# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `setup doctor` — reports pinned vs installed `filen`, the rclone seed, the unit
  files, the credential, and the mount unit state; exits non-zero when unhealthy.
- A hermetic integration suite (`tests/integration/`) covering
  `install → mount-run → export-fragment → status → uninstall` with fake tooling,
  plus a "no plaintext credential" canary test.
- A live end-to-end script (`tests/e2e/live.sh`) that automates the deterministic
  parts of the verification checklist and prompts once for sign-in.
- CI now runs the integration suite, shellcheck, and qmllint/qmlformat where
  available.
- Docs: [supported environments](docs/supported-environments.md), a
  [troubleshooting](docs/troubleshooting.md) state → cause → action matrix with
  known limitations, [pin maintenance](docs/pin-maintenance.md),
  [release runbook](docs/release.md), and a
  [draft upstream issue](docs/upstream-filen-rs-0.2.8-mount-panic.md) for the
  0.2.8 mount panic; `verification.md` is rewritten as the live E2E checklist.
- Provisioning runs a post-start mount smoke check and reports an actionable
  failure instead of raw systemd internals.

### Changed

- Pin `filen` **0.2.9** (a pre-release); 0.2.8 panics on mount.
- Generated units no longer declare `RuntimeDirectory=`; `ExecStartPre` creates
  the tmpfs config dir instead, avoiding the systemd credential
  `File exists` collision (ADR-0005).

### Fixed

- Bound mount restarts with `StartLimitIntervalSec`/`StartLimitBurst`, so a
  failing mount lands in `failed` instead of storming the user manager.
- The status helper distinguishes a rejected credential (`needs-auth`) from
  offline (`quotaKnown:false`, stale `checkedAt`) and always emits one valid JSON
  object on malformed input.
- Uninstall lazily detaches a stale FUSE mount that `mountpoint` cannot see.

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
