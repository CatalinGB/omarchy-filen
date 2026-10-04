# Contributing to Filen for Omarchy

Thanks for helping improve `io.github.catalingb.filen`. This file is the
practical path from clone to a merged change. Read it alongside
[CONTEXT.md](CONTEXT.md) — the domain glossary — and
[docs/architecture.md](docs/architecture.md) — the component and
provisioning diagrams.

## Project shape

The plugin is a mix of QML, a small JavaScript model, and bash/Python helpers:

| Path | What |
|---|---|
| `BarWidget.qml` | The bar widget: one worst-first state glyph. |
| `Panel.qml` | The popup: status, quota, recents, controls, and the editable Settings section. |
| `Service.qml` | The QML service singleton. Runs the status helper on a timer, holds the status contract, and mirrors mount-affecting settings to `settings.conf`. |
| `Model.js` | Pure presentation/formatting logic. Tested directly by `tests/model.test.js`. |
| `bin/status` | The credential-free status helper (Python). Runs local probes and merges the API fragment into the status contract. |
| `bin/setup` | Idempotent install / provision / update / uninstall, and the `doctor` health read-out (bash). Generates the systemd user units. |
| `tests/` | Unit, integration, JS, and live E2E suites (below). |

The service is two generated systemd **user** units — the mount unit
(`omarchy-filen-mount.service`) and the status timer
(`filen-status.{timer,service}`) — plus the FUSE mount itself. Terms such as
**status contract**, **API fragment**, **credential**, and **runtime dir** are
defined in [CONTEXT.md](CONTEXT.md); use that vocabulary in issues, code, and
docs.

## Prerequisites

Required to run the full suite:

- `python3` — the status helper and the Python suites.
- `node` — `tests/model.test.js`.
- `bash` — `bin/setup` and the live E2E.

Optional, but used when present (CI guards each step on availability):

- `shellcheck` — lints `bin/setup` and `tests/e2e/live.sh`.
- Qt 6 `qmllint` or `qmlformat` — QML syntax. Version differences mean CI skips
  this cleanly when the tool is absent; run whichever your Qt ships.
- The `omarchy` CLI — manifest validation (`omarchy plugin validate .`).

No language-level build step exists; the plugin is loaded from source by the
Omarchy shell.

## Validate, lint, and test

Run these from the repository root. The first four are the deterministic suite
CI runs.

```bash
# Manifest/schema validation (needs the omarchy CLI)
omarchy plugin validate .

# Shell lint (if shellcheck is installed). bin/status is Python, so it is not
# included; fail on warnings/errors.
shellcheck --severity=warning bin/setup tests/e2e/live.sh

# QML syntax (if a Qt 6 tool is installed). Qt version differences mean this is
# guarded in CI; use qmlformat in place of qmllint on older toolchains.
qmllint --bare BarWidget.qml Panel.qml Service.qml

# Python unit tests
python3 -m unittest discover -s tests

# Python integration suite (hermetic: fake tooling, no network, no real mount)
python3 -m unittest discover -s tests/integration

# Model.js presentation tests
node tests/model.test.js

# Python coverage (bin/status is the only Python product file; reported, not gated)
python3 -m pip install -r requirements-dev.txt
python3 -m coverage run -m unittest discover -s tests && python3 -m coverage report
```

### Live end-to-end

```bash
tests/e2e/live.sh
```

Live only: it needs a **clean Omarchy box**, FUSE, and a **real Filen account**.
It drives the real `filen` binary, the real FUSE mount, and the real systemd
units, and prompts **once** for the interactive sign-in (email / password /
2FA). This is the layer CI cannot run; see
[docs/verification.md](docs/verification.md) for the checklist it automates and
its report location.

## Local issue tracker

Work is tracked as markdown in the repo, under `.scratch/<effort>/`:

- `map.md` — the effort's destination, decisions so far, and open questions.
- `issues/NN-<slug>.md` — one ticket per file, zero-padded, e.g.
  `issues/09-contributing.md`.

The current effort is
[`.scratch/omarchy-filen-release/`](.scratch/omarchy-filen-release/). Add a
ticket before starting non-trivial work, and update its status as it moves.

## Pin bumps

The plugin pins the `filen` CLI and rclone it downloads. Do **not** hand-edit
`FILEN_VERSION` or `RCLONE_VERSION` in `bin/setup` on a hunch: the `filen` pin is
currently a pre-release chosen to dodge a mount panic (0.2.8), and the rclone
version and checksums must match what the pinned `filen` expects. Follow
[docs/pin-maintenance.md](docs/pin-maintenance.md) end to end, including the
docs mirrors it links and the live smoke mount. Update the mirrored values in
the same change.

## Commit and PR conventions

The repo uses conventional-commit prefixes (as seen in `git log`):

- `feat:` — new user-facing capability
- `fix:` — a bug fix
- `docs:` — documentation only
- `ci:` — CI/workflow changes
- `refactor:` — no behaviour change
- `harden:` — robustness/security hardening
- `test:` — tests only

Keep PRs **scoped** to one change; split unrelated work. Run the deterministic
suite before opening a PR. Add a `CHANGELOG.md` entry for any user-visible
change under `## [Unreleased]`, using the existing `Added` / `Changed` /
`Fixed` / `Removed` headings (see [docs/release.md](docs/release.md) for the
release runbook).

## Reporting bugs

Open an issue with enough state to reproduce. Include:

- Your Omarchy version: `omarchy version`.
- What the panel shows (the state glyph or the Status text).
- The health read-out: `bin/setup doctor`.
- The mount unit's logs:
  `journalctl --user -u omarchy-filen-mount.service`.

Never paste secrets or credential material. The status helper is
credential-free, so its JSON output is safe to share; see
[docs/status-contract.md](docs/status-contract.md) for its shape.

## License

MIT — see [LICENSE](LICENSE). Filen appears in Omarchy as a **FUSE mount, not a
sync client**: there is no offline copy, and the RAM-backed cache is lost on
reboot. Keep that model in mind when reviewing behaviour.
