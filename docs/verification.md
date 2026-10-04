# Verification — `filen.storage`

Three layers, cheapest first. This document is the **live E2E checklist**: the
pass that must be run by hand on a real Omarchy box with a real Filen account,
because it is the only layer that can exercise QML, FUSE, systemd, and the Filen
API. CI covers the two automated layers.

## Layer 1 — automated, hermetic (CI)

| Check | Command | Result |
|---|---|---|
| Python unit tests | `python3 -m unittest discover -s tests` | **124 tests, OK** |
| Model/presentation assertions | `node tests/model.test.js` | **32 assertions, OK** |
| Hermetic integration suite | `python3 -m unittest discover -s tests/integration` | **28 tests, OK** |
| Manifest valid | `omarchy plugin validate .` | exit 0 |
| Helper emits the contract (no `filen`) | `./bin/status` | `{"ok":true,"installed":false,…}` exit 0 |
| Prerequisite detection | `./bin/setup check` | `ok fuse3`, `ok python3`, `ok systemd 261 (>= 256)`, `ok curl`; exit 0 |
| Pin / install / mount health | `./bin/setup doctor` | `doctor: healthy`, exit 0 |
| shellcheck / qmllint | guarded in `.github/workflows/ci.yml` | run when the tool is present |

The Python unit tests (`tests/test_status.py`, `tests/test_setup.py`) are pure
logic with mocks and a temp `HOME`/`XDG_*`. The **integration suite**
(`tests/integration/`) drives the whole non-GUI flow — `install → mount-run →
export-fragment → status → uninstall` — with fake
`systemctl`/`systemd-creds`/`filen`/`rclone` on `PATH`, asserting unit files,
permissions, JSON, and the filesystem. No root, no network. It also runs the
**canary** test proving no plaintext credential persists. This is the automated
end-to-end coverage CI can run.

## Layer 2 — live E2E script (this is the checklist)

`tests/e2e/live.sh` automates the deterministic parts of the pass below and
writes a timestamped report (default `~/.local/state/omarchy-filen/e2e/`). It
prompts **exactly once** for the interactive sign-in, which only a human can do:

```bash
tests/e2e/live.sh
```

It runs: plugin validate → `setup install` → `setup provision` (the one prompt)
→ wait for the mount → `bin/status` contract → systemctl stop/start →
`setup doctor` → file round-trip → uninstall/reinstall. Every step prints
`PASS`/`FAIL`/`SKIP`, and the script exits non-zero if any step failed.

What the script **cannot** do — panel QML interactions, live settings changes, a
real logout/login, network toggling, and each error state — is checklist items
4–9 below, run by hand. Steps 1–3 and 10 overlap the script; keep both so the
script and the manual pass are independently reproducible.

## Layer 3 — the manual live checklist

Run on a **clean Omarchy box** with a real Filen account. Record the result of
each step.

1. **Install.** On a machine with no plugin state:
   `bin/setup install` downloads the pinned `filen` (0.2.9) and rclone seed,
   writes the three marked units, and `daemon-reload`s. `setup doctor` reports
   `healthy`; `setup check` reports every prerequisite `ok`. The panel/bar shows
   **Install** only before this and never a misleading control.
2. **Provision.** Panel → **Set up** (or `bin/setup provision`); complete
   email/password/2FA in the terminal.
   - The blob `~/.config/credstore.encrypted/filen-auth` exists.
   - No plaintext remains: grep for the canary/password finds nothing; the temp
     export was shredded.
   - The decrypted credential exists only at
     `/run/user/<uid>/credentials/<unit>/filen-auth` (0400) while a unit runs,
     and is gone after it stops.
3. **Mount on the first attempt.** `~/Filen` appears without a retry;
   `systemctl --user status omarchy-filen-mount.service` is `active`; the panel
   shows **Mounted**. `rclone.conf` exists only under `$XDG_RUNTIME_DIR/filen/`
   and **not** on persistent disk. No `File exists` in the journal.
4. **Panel controls.** From the panel:
   - **Unmount** → mount goes away; state settles to **Stopped**.
   - **Mount** → state settles to **Mounted**.
   - **Mount at login** on/off → the toggle reflects `is-enabled` (`autoMount`) and
     changing it **does not** unmount a running drive.
   Optimistic state settles to the re-polled truth; no stale state, no dual mount.
5. **Settings change.** Change **Mount folder** and **Cache size limit** in
   Settings; confirm `~/.config/omarchy-filen/settings.conf` is rewritten and the
   mount restarts so the change takes effect (status/quota follow the new path).
   Changing back restores the previous mount. A shell start/hot-reload does
   **not** restart an existing mount.
6. **Logout/login autostart.** Log out and back in (or reboot a disposable VM).
   `~/Filen` is mounted and the panel shows **Mounted** with no manual action,
   via `graphical-session.target`.
7. **File round-trip.** In the mount (terminal **and** Nautilus): create, append,
   read, rename, move, delete. Confirm in-place editing works (VFS cache full).
   Confirm a delete removes the server-side item (it does not go to the desktop
   trash).
8. **Offline.** Turn the network off: the unit does not storm; quota shows stale
   (`quotaKnown:false`, aging `checkedAt`); cached files still read. Turn it back
   on: mount and status fragment recover without manual action.
9. **Error states.** Reproduce each and confirm the single correct action, with
   no misleading controls (e.g. **Mount** hidden before sign-in):
   - remove/rename the credential → **Sign-in needed** → **Set up**;
   - stop the unit → **Stopped** → **Mount**;
   - corrupt the unit / force a mount failure → **Failed** → **Repair** + journal
     hint;
   - no `filen` binary → **Not installed** → **Install**.
10. **Uninstall / reinstall.** `bin/setup uninstall` removes the generated units
    (and lazily detaches any stale FUSE mount) but **keeps** the credential;
    `--purge` also deletes it. Re-running `install` + `start` remounts. The
    uninstall never touches provider-side data.

## Reporting

- The script's log is the report for steps it covers; attach it to the PR.
- Capture a screenshot per error state (step 9) in the live report.
- Any failure should become a ticket; a defect found in the live pass is fixed
  before the PR leaves draft.

## Notes

- QML (`Service.qml`, `BarWidget.qml`, `Panel.qml`) cannot be compiled
  headlessly because it imports the in-shell `qs.*` modules; CI checks syntax
  with `qmllint`/`qmlformat` when available, and the live pass is the only full
  check.
- `bin/status` serves the panel; it never runs `filen` and never sees a
  credential. If you can read a secret out of its output, that is a security
  bug, not a verification failure.
