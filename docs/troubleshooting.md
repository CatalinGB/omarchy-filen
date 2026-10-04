# Troubleshooting

A state → cause → action reference for the states the panel and bar widget show.
Start by reading the current state and the status JSON:

```bash
PLUGIN="$HOME/.config/omarchy/plugins/filen.storage"
"$PLUGIN/bin/status" | python3 -m json.tool   # the panel's exact contract
"$PLUGIN/bin/setup" doctor                   # pin / install / mount health
```

`setup doctor` (exit 1 when unhealthy) reports the installed vs pinned `filen`,
the rclone seed, the unit files, the credential blob, and the mount unit's
`ActiveState`. It is the first thing to run for "it stopped working".

## State matrix

| State you see | Likely cause | Action |
|---|---|---|
| **Not installed** (`installed:false`) | The plugin-managed `filen` binary is missing — never installed, or `~/.local/share/omarchy-filen/` was removed/cleared. | Panel → **Install**, or `"$PLUGIN/bin/setup" install`. Then re-check `setup doctor`. |
| **Sign-in needed** / needs-auth (`authenticated:false`) | No credential blob, **or** the stored credential was rejected — most often after a Filen password change, or the blob was restored onto a different machine/UID (it is machine-bound). | Re-provision: panel → **Set up**, or `"$PLUGIN/bin/setup" provision`. See [Rotation](#rotation--rejected-credential). |
| **Failed** (`unitState:failed`) | The mount unit entered `failed`. Usually a rejected credential (surfaces as needs-auth), a stale FUSE mount, a missing/foreign unit file, or a real mount error. Restart storms are bounded, so `failed` is stable. | Read the log: `journalctl --user -u omarchy-filen-mount.service -n 100 --no-pager`. Then see [Failed mount](#failed-mount) below. |
| **Stopped** (`unitState:inactive`, `authenticated:true`) | The unit is not running: you unmounted, autostart is off, or this is a fresh login before the unit started. | Panel → **Mount**, or `systemctl --user start omarchy-filen-mount.service`. |
| **Mounted** but quota stale (`quotaKnown:false`, old `checkedAt`) | The network/API probe failed or the status timer has not run. This is the normal **offline** presentation, not a failure. | Check connectivity; wait for the next `filen-status.timer` run. See [Offline / stale quota](#offline--stale-quota). |
| **Mount point shows `Transport endpoint is not connected`** | A previous `filen`/rclone process died hard (kill, crash, reboot mid-mount) and left a dead FUSE entry. The directory exists but nothing serves it. | The unit cleans this on start; otherwise `fusermount3 -uz "$HOME/Filen"`. See [Stale FUSE mount](#stale-fuse-mount). |
| **RAM use climbs / cache eats memory** | The VFS cache is RAM-backed and capped by **Cache size limit** (default 4 GB). Large reads fill it up to the cap. | Lower **Cache size limit** in Settings (restarts the mount). See [RAM cache](#ram-cache). |
| **`Failed to set up credentials: File exists`** in the journal | The unit declares both `RuntimeDirectory=` and `LoadCredentialEncrypted=`; on systemd 261 the user manager's runtime dir and credential scratch space collide. | Should not happen: generated units omit `RuntimeDirectory=` (see [ADR-0005](adr/0005-mount-unit-credential-quirks.md)). If you hand-edited a unit, re-run `setup install` to regenerate it. |
| **`filen ... panicked ... pipe_output_to_logs`** | An old `filen` 0.2.8 binary is installed instead of the pinned 0.2.9. | `"$PLUGIN/bin/setup" update` to re-fetch the pin. See [pin maintenance](pin-maintenance.md). |
| **rclone is re-downloaded on every start** | The pre-seeded rclone is missing from the plugin data dir, so `filen` fetches its own. | `"$PLUGIN/bin/setup" install` (idempotent) to re-seed. `setup doctor` flags a missing seed. |

## Rotation / rejected credential

A Filen password change (or a new machine) invalidates the stored credential.
The plugin detects a rejected credential as **needs-auth**, never as a generic
`failed`, and never prompts in the service. To recover:

```bash
"$PLUGIN/bin/setup" provision   # sign in again; replaces the encrypted blob
```

`provision` re-exports the auth config, re-encrypts it with
`systemd-creds encrypt --user`, shreds the plaintext, and restarts the mount.
Offline is deliberately **not** treated as needs-auth, so a stale fragment never
asks you to re-authenticate.

## Failed mount

1. `journalctl --user -u omarchy-filen-mount.service -n 100 --no-pager` — the
   real error is on the unit's stderr.
2. `setup doctor` — distinguishes a bad install (missing binary/seed/units, stale
   pin, missing credential) from a runtime failure.
3. If the log mentions a dead transport, clean the stale mount
   (`fusermount3 -uz`), then `systemctl --user restart omarchy-filen-mount.service`.
4. If it is an auth error, follow [Rotation](#rotation--rejected-credential).

Repeated failures land in `failed` after the unit's start burst and **stop**
restarting — that is intentional, so a broken credential cannot storm the user
manager.

## Stale FUSE mount

A hard kill (or a reboot mid-mount) can leave `~/Filen` as a dead FUSE entry
that `mountpoint -q` cannot see. Symptoms: the path exists, `ls` errors with
`Transport endpoint is not connected`, and a remount refuses the busy mount
point.

The mount unit runs `fusermount3 -uz` before each start, and `setup uninstall`
lazily detaches. To clear one by hand:

```bash
fusermount3 -uz "$HOME/Filen"      # adjust for a custom Mount folder
systemctl --user restart omarchy-filen-mount.service
```

## Offline / stale quota

Offline is degraded, not failed:

- The mount process is not crashed into a restart loop.
- The panel keeps the local fields and shows the last known quota with a stale
  `checkedAt` (`quotaKnown:false` while the fragment ages out).
- rclone serves already-cached files until the RAM cache is evicted.

On reconnect the mount and the `filen-status.timer` fragment recover without
manual action. If quota stays stuck after you are back online, force a probe:

```bash
systemctl --user start filen-status.service   # oneshot; rewrites the fragment
```

## RAM cache

The config dir **is** tmpfs, so the VFS cache lives in RAM and is capped by the
**Cache size limit** setting (default 4 GB). Reading large files fills it; the
cap is enforced and eviction is LRU-ish, but a 4 GB cap plus the mount's own
working set is real memory. Lower the cap in Settings (this restarts the mount)
if memory is tight. The cache is empty after every reboot by design.

## systemd credential errors

- `Failed to set up credentials: File exists` — the
  `RuntimeDirectory=` + `LoadCredentialEncrypted=` collision. Generated units
  never declare `RuntimeDirectory=`; regenerate with `setup install` if a
  hand-edited unit does.
- `systemd-creds` missing or too old — the design needs **systemd ≥ 256** for
  `systemd-creds ... --user`. `setup check` reports it.
- Credential decryption fails after a hardware/TPM change or a copy to another
  machine — the blob is machine- and UID-bound; re-run `setup provision`.

## Known limitations

These are design boundaries, not bugs to fix:

- **Mount, not sync.** There is no offline folder and no two-way background
  sync. Files are read through the mount on demand; the VFS cache is RAM and
  does not survive reboot.
- **Single account.** One Filen account per user; there is no multi-account
  support.
- **No plan data.** The CLI does not expose the subscription/plan, so the panel's
  `plan` field is always `null`.
- **tmpfs cache.** `rclone.conf` and the VFS cache live under
  `$XDG_RUNTIME_DIR/filen/`, so keys never hit persistent disk — at the cost of
  an ephemeral cache.
- **Prerelease pin.** The pinned `filen` 0.2.9 is a GitHub pre-release, chosen
  because 0.2.8 panics on mount. Updating the pin is deliberate; see
  [pin maintenance](pin-maintenance.md).
- **No desktop trash.** Deleting through `~/Filen` removes the server-side item
  (Filen keeps its own trash); it does not go to the XDG desktop trash.
