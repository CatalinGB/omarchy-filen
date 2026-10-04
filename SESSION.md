# Omarchy × Filen — session notes

Date: 2026-10-04
Goal: is there an Omarchy-native Filen integration; if not, how easily can one be
built following "the oma way", without caring about heavy security concerns.

---

## 1. The original question (and the misread)

The first pass read "filen" as "file n" / a file manager. That was wrong, but the
findings are still worth keeping (section 6). The real question was about
**Filen** (filen.io), the end-to-end-encrypted cloud storage service.

---

## 2. Does Omarchy have a Filen anything?

No. Nothing Filen is installed (`filen`, `filen-cli`, `filen-desktop` absent; no
rclone Filen backend on this box). But Omarchy already ships the exact pattern a
Filen integration would follow: **`omarchy.dropbox`**.

Location: `/usr/share/omarchy/shell/plugins/panels/dropbox/`

It is a built-in Omarchy shell **bar-widget** for cloud storage. This is the
"oma way" for a Dropbox-like service, and Filen slots straight into it.

---

## 3. Anatomy of the Dropbox panel (the template)

Five files:

| File | Role |
|---|---|
| `manifest.json` | plugin metadata: `id: omarchy.dropbox`, `kinds: ["bar-widget"]`, `entryPoints.barWidget: Panel.qml`, `barWidget` display metadata + settings schema (`refreshIntervalSec`) |
| `Panel.qml` | bar icon + popup UI; keyboard cursor nav; hero animation phrases; consumes the status JSON |
| `Model.js` | pure presentation helpers: parse status, file-kind/glyph, byte/percent/relative-time formatting |
| `Service.qml` | polls `status.py` on a timer, exposes state to `Panel.qml`, runs login/control commands |
| `status.py` | the only data source; emits one JSON contract |

### The status contract (`status.py` output)

```
installed, running, authenticated, statusText,
accountPath, plan, usedBytes, quotaBytes, usagePercent,
quotaKnown, files[]
```

### What it actually does

- **State**: installed / running / authenticated
  - installed = `dropbox-cli` on PATH
  - running   = parses `dropbox-cli status` ("not running" ⇒ false)
  - authenticated = `~/.dropbox/info.json` account path exists
- **Login**: runs `dropbox-cli start`, scrapes the first `http(s)://` URL from its
  output and opens it with `Qt.openUrlExternally`
- **Pause/resume sync**: `dropbox-cli stop` / `start`, with an *optimistic* UI
  (`_desired`) and a settle re-poll loop
- **Storage**: used bytes by `os.walk`-ing the **local Dropbox folder** (not the
  API); quota from a **hardcoded plan → bytes table**; usagePercent derived
- **Recent files**: same local walk, top N by mtime via a bounded heap
- **Open file**: `uwsm-app -- nautilus --select <file://…>`
- **UI niceties**: keyboard cursor (header/files sections), scroll-into-view,
  elided error text, action-status toast, startup ramp poll until daemon appears

Key insight: **usage and recent files come from the local synced folder, not the
API.** That is why the whole thing is easy: it is a directory walk plus one CLI.

---

## 4. Filen clients — verified from the repos

- **`filen-desktop`** (`FilenCloudDienste/filen-desktop`) — Electron/Node
  (`package.json`, `.node-version`, dev needs `@filen/web`). Features: Syncing,
  Virtual Drive mounting, S3, WebDAV, File Browsing, Chats, Notes, Contacts.
  Functional Dropbox analogue, but the **least** Omarchy-shaped client.
- **`filen-cli`** (`FilenCloudDienste/filen-cli`) — Node/Bun TS today
  (`bun.lock`). Stateless + interactive mode, **sync** (like the desktop app),
  **mount**, WebDAV mirror server, S3 mirror server. Install: `filen.io/cli.sh`,
  npm `@filen/cli`, Docker, release binaries.
  - **Warning**: being sunset in favor of a **Rust rewrite**
    (`FilenCloudDienste/filen-rs`, `filen-cli` subdir), ~5 MB binary.
  - Use the Node CLI **v0.0.36** today (pinned as latest).

---

## 5. Recommendation

**Integrate against `filen-cli`** — it is simultaneously the most
Omarchy-in-spirit *and* the easiest to integrate (these usually pull apart; here
they align).

**Spirit.** Omarchy is terminal-forward, Rust-leaning, anti-Electron. Every
cloud/system panel it ships drives a CLI (`omarchy.dropbox` → `dropbox-cli`;
tailscale panel → tailscale CLI). `filen-cli` is exactly that shape, runs
headless, and its Rust rewrite is a tiny native binary — the same instinct that
made OmaCal a Tauri/Rust+CLI app. `filen-desktop` is the opposite: Electron
GUI/tray with no stable scriptable contract.

**Easiest.** The panel is just `status.py` emitting the dropbox JSON contract:
- `installed`      = `shutil.which("filen")`
- `authenticated`  = the CLI's own config
- `files[]` / `used` = the CLI's listing, or run its **sync** and `os.walk` the
  local sync dir (the exact `scan_dropbox` code), or its **mount**
- `running`        = a `filen sync`/mount process you own (e.g. systemd user unit)

**Practical path.** Write `status.py` against `filen-cli`; when the Rust
`filen-cli` ships, swap the binary path — the panel contract is unchanged. Do
**not** base anything on `filen-desktop`.

---

## 6. Coverage: Dropbox panel → Filen panel

| Capability | Covered by filen-cli? |
|---|---|
| installed / authenticated | Yes — `which filen`, config lookup |
| Recent files + open | Yes — walk the local sync dir, `nautilus --select` (same code) |
| used bytes | Yes — local walk, or API |
| Pause/resume | Yes, but *you* own it (spawn/signal a `filen sync` process) |
| Login | Partial — CLI login is interactive (email/2FA); can't be driven from a panel like `dropbox-cli start` |
| Quota / plan | **Needs adding** — Dropbox hardcodes plan sizes; Filen needs an account/API call (CLI may not expose quota) |
| running daemon | **Needs adding** — Dropbox has `dropboxd`; filen-cli is stateless, so a systemd user unit / spawned process supplies it |

**Bottom line:** ~80% carries over unchanged (status, recent files, open, usage,
the whole QML/Model layer). Three things must be added: a **quota source**, a
**sync-process lifecycle**, and an **auth flow** that can't live in the panel.
`open file` also assumes a local sync path — if you use the CLI's *mount*
instead, path handling changes.

---

## 7. Build plan (proposed, not yet executed)

1. Copy the template:
   `cp -r /usr/share/omarchy/shell/plugins/panels/dropbox ~/.config/omarchy/plugins/filen.storage`
   (or `omarchy plugin clone omarchy.dropbox` and rename).
2. `manifest.json`: `id` → `filen.storage`, display name/labels → Filen, swap the
   icon (`DropboxIcon.qml` → a Filen mark). Colors come from the bar/theme.
3. Rewrite `status.py` to emit the **same keys** from `filen-cli`. Leave the
   exact subcommands as clearly-marked TODOs until confirmed against
   `filen --help` / docs.cli.filen.io.
4. Handle the three additions: quota source, sync-process lifecycle, auth flow.
5. `omarchy-shell shell rescanPlugins` then
   `omarchy plugin enable filen.storage --section right`.
6. `omarchy plugin validate <plugin-folder>` to check the manifest.

### Cheap extras
- Launcher entry in `~/.config/omarchy/extensions/omarchy-menu.jsonc`
  (`personal.filen` → open web / `filen-cli`), one line.
- OmaCal-style self-install: embed the plugin in an app binary and drop it into
  `~/.config/omarchy/plugins/` (see the OmaCal plugin `packaging/omarchy-plugin/`
  as the reference, and `src-tauri/src/omarchy_plugin.rs` for its install rules).

---

## 8. Security note

Explicitly out of scope per the request. The Dropbox helper is just a Python
script with timeouts; a Filen panel shelling to `filen-cli` or reading a local
sync dir is no more privileged. The only sensitive piece is an API key if the
SDK/API route is chosen for quota — it can live in `filen-cli`'s own config.

---

## 9. Appendix — the file-manager misread (still useful)

Omarchy has **no** native file-manager app or shell plugin. Its file manager *is*
Nautilus:

- Default for `inode/directory` (`default/applications/mimeapps.list`)
- `SUPER+SHIFT+F` → `omarchy-launch-nautilus`
- `SUPER+ALT+SHIFT+F` → `omarchy-launch-nautilus-cwd`
  (`default/hypr/bindings/applications.lua`)
- Extension point: Nautilus Python extensions shipped by Omarchy
  (`default/nautilus-python/extensions/localsend.py`, `transcode.py`), installed
  to `~/.local/share/nautilus-python/extensions/`
- Pickers (not a manager): `omarchy file select` (XDG portal),
  `omarchy menu file` (fzf-style)

---

## 10. Reference paths

- Template panel: `/usr/share/omarchy/shell/plugins/panels/dropbox/`
- Plugin docs (skill): `/home/kalio/.agents/skills/omarchy/plugins.md`
- OmaCal Omarchy plugin reference: `/home/kalio/Work/omacal/packaging/omarchy-plugin/`
- Plugin commands: `omarchy plugin --help` (clone/enable/disable/list/validate)
- Filen CLI docs: https://docs.cli.filen.io/ · https://docs.filen.io/docs/cli
- Filen clients:
  - https://github.com/FilenCloudDienste/filen-cli (Node, sunsetting)
  - https://github.com/FilenCloudDienste/filen-rs (Rust rewrite, WIP)
  - https://github.com/FilenCloudDienste/filen-desktop (Electron; avoid)
