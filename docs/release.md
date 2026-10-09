# Release runbook

How `io.github.catalingb.filen` gets a version and reaches users. One release is
`manifest.json` version + a matching `CHANGELOG.md` entry + a `vX.Y.Z` tag.

The plugin version and the pinned runtime versions are **independent**: the
plugin can ship a docs fix without touching the pin, and a pin bump is its own
change (see [pin maintenance](pin-maintenance.md)). Do not conflate them.

## Versioning

[Semantic Versioning](https://semver.org/spec/v2.0.0.html), tracked in
`manifest.json` `version` (currently `0.2.1`) and listed in `CHANGELOG.md`
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

- **MAJOR** — a change that breaks existing installs without a migration.
- **MINOR** — new user-facing capability, backwards compatible.
- **PATCH** — fixes, docs, pin bumps, internal changes.

Pre-1.0 (`0.x`), so treat a breaking change as MINOR and an everything-else as
PATCH until the contract stabilises.

## Pre-release checklist

Do not tag until all of these hold:

- [ ] All hardening tickets for the milestone are resolved (H21 code review
      included).
- [ ] CI is green: `python3 -m unittest discover -s tests`,
      `python3 -m unittest discover -s tests/integration`,
      `node tests/model.test.js`, `omarchy plugin validate .`, and shellcheck /
      qmllint where available.
- [ ] The live E2E pass in [verification.md](verification.md) **passed** on a
      clean Omarchy box; its report is attached.
- [ ] `bin/setup doctor` reports `healthy` on that box.
- [ ] `CHANGELOG.md` has an entry for the version.
- [ ] Pinned `filen`/rclone versions are consistent everywhere (below).

## The release

1. **Bump the version** in `manifest.json`:
   ```json
   "version": "0.2.0"
   ```
2. **Update `CHANGELOG.md`.** Promote the `Unreleased` section to
   `## [0.2.0] - YYYY-MM-DD` and add a fresh `## [Unreleased]` above it. Keep the
   `Added` / `Changed` / `Fixed` / `Removed` headings; link notable docs.
3. **Commit** both files together, e.g.
   `release: v0.2.0` (no tag yet). Run the automated suite once more.
4. **Tag** the commit and push:
   ```bash
   git tag -a v0.2.0 -m "io.github.catalingb.filen v0.2.0"
   git push origin v0.2.0
   ```
   Push the branch first; users fetch the default branch and read
   `manifest.json`.
5. **Confirm `omarchy plugin update`** picks it up:
   ```bash
   omarchy plugin update io.github.catalingb.filen
   ```
   This re-clones/pulls the plugin under
   `~/.config/omarchy/plugins/io.github.catalingb.filen/` and reloads it. Verify the new
   `version` in `manifest.json` and that the bar/panel still come up. A version
   already current is a no-op.

## Keeping the pins consistent

A `filen`/rclone pin bump changes the values in `bin/setup` and must be mirrored
in the docs in the same change:

- `bin/setup`: `FILEN_VERSION`, `RCLONE_VERSION`, and (for rclone) the embedded
  checksums.
- [supported-environments.md](supported-environments.md#pinned-versions) — the
  pinned-versions table.
- [prerequisites.md](prerequisites.md) — the `filen` CLI row.
- [pin-maintenance.md](pin-maintenance.md) — the runbook's examples.
- [upstream-filen-rs-0.2.8-mount-panic.md](upstream-filen-rs-0.2.8-mount-panic.md)
  — only if the pin moves *past* the version that fixes the panic.

`setup doctor` compares the pinned `FILEN_VERSION` against the installed marker
`~/.local/share/omarchy-filen/filen.version`, so a stale install is visible
without reading the source.

## Hotfix

For a released defect: branch from the tag, make the smallest fix, add a
`### Fixed` PATCH entry, then repeat the pre-release checklist and release as
`vX.Y.(Z+1)`. Do not silently re-tag a shipped version.
