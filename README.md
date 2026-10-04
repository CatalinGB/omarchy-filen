# Filen for Omarchy

An Omarchy-native integration for [Filen](https://filen.io) — end-to-end
encrypted cloud storage. A bar widget and panel show your mount status, storage
usage, and recent files; your Filen drive mounts as an ordinary folder. Built on
the [filen-rs](https://github.com/FilenCloudDienste/filen-rs) `filen` CLI.

```
Bar widget ─▶ systemd user units ─▶ filen mount ─▶ ~/Filen
 (status)      (the service)         (rclone/FUSE)   (what you browse)
```

The plugin installs everything it needs: the `filen` binary, rclone, and its
systemd units. You log in once, and it starts at login.

> **Beta.** `filen-rs` is a public beta. This plugin pins a known-good `filen`
> version and updates it deliberately.

## Requirements

- Omarchy 4 (Quattro shell plugin system)
- `systemd` 256+ (for `systemd-creds --user`)
- `python3` and `fuse3` (both ship with Omarchy; used for the status helper and
  the mount respectively)

The plugin detects anything missing and offers to install it.

## Install

```bash
omarchy plugin add https://github.com/<you>/omarchy-filen.git --enable
```

Omarchy clones the repository into `~/.config/omarchy/plugins/filen.storage/`,
validates it, and adds the bar icon. Plugins run unsandboxed with your user
permissions — review the source before accepting the prompt.

## Set up (once)

Click the Filen icon in the bar → **Set up**. A terminal opens and walks you
through the one-time steps:

1. Installs the pinned `filen` binary and pre-seeds rclone.
2. Writes and loads the systemd units.
3. Prompts you to log in to Filen (email / password / two-factor).
4. Encrypts that credential into a machine-bound **systemd credential** and
   shreds the plaintext.

After that, your drive mounts at login and the panel works — **no repeated
login**, no password ever typed into the panel.

## Using the panel

- **Status** — mounted, mounting, stopped, sign-in needed, or failed.
- **Storage** — used and total, with a percentage.
- **Recent files** — your most recent Filen items; click one to open it in
  Nautilus.
- **Mount / Unmount** — control the mount for this session.
- **Mount at login** — toggle automatic mounting.
- **Open Filen** — jump to the Filen web UI or a terminal.

The bar icon shows the state that most needs attention (failed → sign-in needed →
stopped → mounted), so problems surface without opening the panel.

## Settings

Right-click the bar widget → **Settings**, or edit the entry in
`~/.config/omarchy/shell.json`.

| Setting | Default | Notes |
|---|---|---|
| Mount folder | `~/Filen` | Where Filen appears |
| Cache size limit | 4 GB | Upper bound on the RAM-backed VFS cache (see below) |
| Status refresh | 15 s | Local-only check; cheap |
| Storage/recents refresh | 10 min | Network calls; keep it slow |
| Show text in bar | off | Prints state next to the icon |

## Where things live

| Path | What |
|---|---|
| `~/Filen/` | Your mounted Filen drive |
| `~/.config/credstore.encrypted/filen-auth` | The encrypted credential (the only persistent copy) |
| `~/.local/share/omarchy-filen/` | The managed `filen` binary and rclone |
| `~/.config/systemd/user/filen-mount.service` | The mount unit |
| `~/.config/systemd/user/filen-status.{timer,service}` | The slow status/recents timer |
| `$XDG_RUNTIME_DIR/filen/` | tmpfs: mount point config, `rclone.conf`, VFS cache, status |
| `~/.config/omarchy/shell.json` | Bar layout and plugin settings |

**The config directory is tmpfs**, so `rclone.conf` (which contains your Filen
keys) never touches persistent disk. The trade-off: the file cache lives in RAM
and is lost on reboot, so cached files are not available offline across restarts.
See [SECURITY.md](SECURITY.md).

## Using it from the terminal

Helpers stay inside the installed plugin rather than modifying your `PATH`:

```bash
PLUGIN="$HOME/.config/omarchy/plugins/filen.storage"

"$PLUGIN/bin/setup"                       # install / repair / re-provision
"$PLUGIN/bin/status"                      # the panel's JSON
systemctl --user status filen-mount.service
systemctl --user restart filen-mount.service
journalctl --user -u filen-mount.service -f
```

## Troubleshooting

- **Sign-in needed** — your credential is missing or was rejected (often after a
  password change). Run **Set up** again.
- **Mount failed** — `journalctl --user -u filen-mount.service`. A stale FUSE
  mount is cleaned automatically on the next start.
- **Bar icon dim** — the service is stopped; use **Mount**.
- **Filen shows unavailable** — check `systemd-creds` support (`systemd-creds
  --version`) and that FUSE is installed.

## Uninstall

```bash
PLUGIN="$HOME/.config/omarchy/plugins/filen.storage"
"$PLUGIN/bin/setup" --uninstall        # removes units; keeps your credential
"$PLUGIN/bin/setup" --uninstall --purge # also deletes the credential
omarchy plugin remove filen.storage
```

Uninstalling never touches anything stored in Filen.

## License

See [LICENSE](LICENSE).
