# Verification — `filen.storage`

Ticket 09. Two parts: what is verified automatically (in-repo), and the
checklist that needs a live Omarchy session with a real Filen account.

## Automatically verified

| Check | Command | Result |
|---|---|---|
| Manifest valid | `omarchy plugin validate .` | exit 0 |
| Status helper contract | `python3 -m unittest discover -s tests` | 40 tests, OK |
| Presentation helpers | `node tests/model.test.js` | 32 assertions, OK |
| Helper emits the contract | `./bin/status` (no `filen` installed) | `{"ok":true,"installed":false,"authenticated":false,"running":false,"statusText":"Not installed",…}` exit 0 |
| Prerequisite detection | `./bin/setup check` | `ok fuse3`, `ok python3`, `ok systemd 261 (>= 256)`, `ok curl`; exit 0 |
| Setup idempotency / foreign-refusal / install-uninstall | `python3 -m unittest tests.test_setup` (mocks + temp `HOME`/`XDG_*`; fake `systemctl`/`systemd-creds`/`curl`/`filen`) | 18 tests, OK — no real system state touched |

## Requires a live session (not verifiable in this environment)

These need an Omarchy shell, a real Filen account (interactive 2FA), and a
login session; they cannot be exercised headlessly. Run them once after install:

1. **Provision** — panel → **Set up**; complete email/password/2FA in the
   terminal; confirm `~/.config/credstore.encrypted/filen-auth` exists and no
   plaintext remains (`grep -r <canary>` finds nothing; the temp export was
   shredded).
2. **Mount** — `~/Filen` appears; `systemctl --user status filen-mount.service`
   is `active`; `rclone.conf` exists only under `$XDG_RUNTIME_DIR/filen/` and
   **not** on persistent disk.
3. **Resilience** — `omarchy restart shell` and a plugin hot-reload do **not**
   drop the mount; the panel recovers.
4. **States** — remove/rename the credential → `needs-auth`; stop the unit →
   `stopped`; corrupt the unit → `failed`; with no `filen` binary → `Install`.
5. **Controls** — Mount/Unmount and Mount-at-login from the panel take effect
   and settle.
6. **Recents** — the list populates from `filen-status.timer`; clicking opens
   Nautilus at the file.
7. **Security** — while the mount runs, the decrypted credential exists only at
   `/run/user/<uid>/credentials/<unit>/filen-auth` (0400) and is gone after stop;
   the helper and QML never read it.

## Notes

- QML (`Service.qml`, `BarWidget.qml`, `Panel.qml`) cannot be compiled headlessly
  here because it imports the in-shell `qs.*` modules; syntax was checked with
  the same tooling the shipped panels tolerate, and the panels mirror the
  first-party/furmware patterns.
- Any defect found in the live pass should be fixed before the PR leaves draft.
