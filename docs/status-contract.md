> Canonical copy; the working copy under `.scratch/` is gitignored.

# Filen plugin — status contract (ticket 03)

The **service** owns auth and runs `filen` with its systemd credential; it writes
one **non-secret** JSON document that the panel reads. The panel never runs
`filen` and never sees a credential.

## 1. CLI invocation contract

- **`--json` is a global flag and must come *before* the subcommand.**
  Correct: `filen --skip-update --json stat /`.
  Wrong: `filen stat / --json` → clap usage error (`unexpected argument '--json'`).
  *(Verified live; the source has `json` on `CliArgs`, not on the subcommands.)*
- Always pass `--skip-update` (the updater otherwise hits GitHub and, on failure,
  can abort a non-interactive run).
- Always pass `--auth-config-path <cred>` (from the systemd credential) so the
  CLI never falls back to a keyring or an interactive prompt.
- Pin `--config-dir` to the unit's tmpfs (`%t/filen`).
- **Exit-code contract:** exit `0` ⇒ JSON on stdout. **Any non-zero exit ⇒ no JSON
  on stdout**; the message is human text on stderr. Treat non-zero as
  "unavailable", never parse stdout.
- **Never an interactive prompt in the service:** a non-TTY `filen` with no valid
  credential exits `1` with
  `✘ Failed to read input from terminal. Please ensure that the terminal supports interactive input.`
  (verified). Wrong credentials exit `1` with `✘ Email or password wrong`
  (verified). The service must always supply a credential, and the panel must
  never invoke `filen` at all.

### Sources the service may call

| Command (`--skip-update --json` global) | stdout JSON |
|---|---|
| `filen … stat /` | `{"type":"drive","usedStorage":<int>,"totalStorage":<int>,"files":<int>,"directories":<int>}` |
| `filen … stat <file>` | `{"name","type":"file","size","modified","created","uuid"}` (`modified`/`created` nullable) |
| `filen … stat <dir>` | `{"name","type":"directory","size","files","directories","created","uuid"}` |
| `filen … ls [dir]` | `{"directories":["name",…],"files":["name",…]}` — **names only, no size/mtime** |
| `filen … list-recents` | `{"directories":["/abs/path",…],"files":["/abs/path",…]}` — **paths only** |

*(Shapes read from `filen-cli/src/commands/fs_cmds.rs`; `--json` output for
authenticated calls not live-verified — needs a real account.)*

## 2. Service-written status JSON (the panel's contract)

Emitted by the `bin/status` helper on **stdout** (the panel's `Service.qml` reads
it); there is no `status.json` file. Reuses the Dropbox panel's key set for
QML/Model reuse, plus a few Filen-native fields.

**Two producers (ticket 06):**
- the **panel helper** (credential-free) supplies the local fields —
  `installed`, `running`, `unitState`, `mountPath`, `authenticated`,
  `autoMount`;
- the **status timer** (credentialed, `filen-status.timer` → oneshot) writes a
  non-secret fragment `$XDG_RUNTIME_DIR/filen/api-status.json`:
  `{ok, usedBytes, quotaBytes, usagePercent, quotaKnown, files[], checkedAt}`.

The panel helper merges the fragment into the document above; if the fragment is
missing or stale, it keeps the local fields and marks the API fields unknown.

```json
{
  "ok": true,
  "installed": true,
  "authenticated": true,
  "running": true,
  "statusText": "Mounted",
  "mountPath": "/home/u/Filen",
  "unitState": "active",
  "autoMount": false,
  "plan": null,
  "usedBytes": 0,
  "quotaBytes": 0,
  "usagePercent": 0.0,
  "quotaKnown": false,
  "files": [
    { "name": "…", "path": "…", "folder": "…", "modifiedTs": 0, "sizeBytes": 0 }
  ],
  "checkedAt": 0
}
```

Failure document (the service always writes valid JSON):

```json
{ "ok": false, "error": "<short message>", "checkedAt": 0 }
```

### Field mapping

| Field | Source | Notes |
|---|---|---|
| `ok` | service | `false` ⇒ panel shows `error`; other fields may be absent |
| `installed` | ticket 10 | the plugin-managed `filen` binary is present |
| `authenticated` | credential blob presence | blob present (setup done). A revoked-but-present credential surfaces as `unitState=failed` / `quotaKnown=false`; **never** a prompt |
| `running` | ticket 01 | `mountpoint -q "$mountPath"` and/or unit `ActiveState` |
| `statusText` | service | human string (e.g. `Mounted`, `Sign-in needed`, `Stopped`) |
| `mountPath` | settings | the local mount root (`~/Filen` default) |
| `unitState` | `systemctl --user show` | `active`/`inactive`/`failed` |
| `autoMount` | `systemctl --user is-enabled omarchy-filen-mount.service` | `true` when the unit is enabled to start at login; absent/disabled ⇒ `false` |
| `plan` | — | `null`; the CLI exposes no plan (SDK only) |
| `usedBytes` | `stat /` → `usedStorage` | |
| `quotaBytes` | `stat /` → `totalStorage` | |
| `usagePercent` | derived | `used/quota*100`, clamped; `0` when unknown |
| `quotaKnown` | `stat /` success | |
| `files[]` | `list-recents` + `stat` (ticket 04) | `{name,path,folder,modifiedTs,sizeBytes}`; `list-recents` → top K → `stat` each; slow cadence, cached |
| `checkedAt` | service | epoch seconds |

## 3. Live samples captured (binary 0.2.8, x86_64)

```
$ filen --version
Filen CLI 0.2.8

$ filen --skip-update --config-dir <tmp> --json stat /   # no credential, no tty
✘ Failed to read input from terminal. Please ensure that the terminal supports interactive input.
[exit=1]

$ filen --skip-update --json --config-dir <tmp> --email nobody@example.com --password wrongpass stat /
✘ Email or password wrong
[exit=1]

$ filen --skip-update --config-dir <tmp> stat / --json   # wrong flag placement
error: unexpected argument '--json' found
Usage: filen stat <FILE_OR_DIRECTORY>
```

Config dir after unauthenticated runs contains only `logs/` — no credential
files are created.

## 4. Open items

- Authenticated `stat /`, `ls`, and `list-recents` JSON samples need a real
  account; not captured here (would require user credentials).
- `files[]` source decided in ticket 04: `list-recents` → top K → `stat` each.
- The service's write cadence / debounce is ticket 06.
