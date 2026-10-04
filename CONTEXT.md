# Filen for Omarchy

An Omarchy shell plugin that integrates Filen (end-to-end-encrypted cloud
storage) through the filen-rs CLI: a bar widget and panel, a systemd-supervised
FUSE mount, and a credential-free UI layer.

## Language

**Filen**:
The end-to-end-encrypted cloud storage service (filen.io). The account being
integrated.
_Avoid_: file manager, "file n".

**filen-rs / `filen` CLI**:
The Rust rewrite of the Filen client, shipped as the `filen` binary. The plugin's
only integration surface.
_Avoid_: filen-cli (that names the Node, sunsetting CLI), filen-desktop.

**Plugin (`filen.storage`)**:
The Omarchy shell plugin: manifest, QML, and `bin/` helpers, installed under
`~/.config/omarchy/plugins/`.

**Bar widget**:
The plugin's component mounted in a bar section; shows one worst-first state
glyph.

**Panel**:
The popup surface: status, quota, recents, and controls. Opened from the bar
widget.

**Service**:
The generated systemd user units — `filen-mount.service` and
`filen-status.{timer,service}` — that own authentication and the mount.
_Avoid_: "service" for Omarchy's manifest `service` kind (an in-shell QML
singleton); call that a **QML service singleton**.

**Status helper**:
The credential-free `bin/status` process. Runs cheap local probes and merges the
API fragment into the status contract.
_Avoid_: status.py (that names the Dropbox panel's helper).

**API fragment**:
The non-secret JSON (`api-status.json`) written by the credential-holding status
timer: quota and recent files. Its freshness is its `checkedAt`.

**Status contract**:
The single JSON document the panel consumes, assembled by the status helper.

**Credential**:
The Filen SDK auth config (master keys, private key, API key), stored
systemd-encrypted in `~/.config/credstore.encrypted/filen-auth`.
_Avoid_: token (Filen's is key material, not a bearer token).

**Provisioning**:
The one-time flow that produces the credential: interactive `filen` login →
`systemd-creds encrypt --user` → shred.

**Mount unit**:
`filen-mount.service` — the systemd user unit running the FUSE mount.

**Status timer**:
`filen-status.timer` (with its oneshot service) — the slow, credentialed producer
of the API fragment.

**Ownership marker**:
The comment line a generated unit carries so the plugin acts only on files it
created.
_Avoid_: marker, signature.

**Runtime dir**:
`$XDG_RUNTIME_DIR/filen/` — the tmpfs holding the mount's `rclone.conf`, VFS
cache, mount point, and status documents.
_Avoid_: config dir (that names the CLI's `--config-dir` location generally).
