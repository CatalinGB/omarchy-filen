# Keep `RuntimeDirectory` out of the mount unit; accept the tmpfs workaround

On systemd 261 a **user** unit that sets both `RuntimeDirectory=filen` and
`LoadCredentialEncrypted=filen-auth` fails credential setup at start with
`Failed to set up credentials: File exists`, and the unit never reaches
`ExecStart`. Live testing found this while wiring the mount; it affected the
mount and status units alike. The cause is the user manager creating the
runtime directory out of the same per-unit credential scratch space that
`LoadCredentialEncrypted=` prepares, so the second step collides with the first.

We keep the verified workaround: the generated units do **not** declare
`RuntimeDirectory=`. Instead the mount unit (and the status oneshot) create the
config dir with `ExecStartPre=/usr/bin/mkdir -p %t/filen`. `%t` is
`$XDG_RUNTIME_DIR`, a tmpfs, so ADR-0003's guarantee still holds — `rclone.conf`
and the VFS cache never touch persistent media — we just create that tmpfs
directory by hand rather than through systemd. The mount unit (not the status
oneshot) owns the directory's lifetime; a smoke check in `setup provision`
polls `mountpoint` for up to 30s and reports a clear success or an actionable
failure. A regression test asserts no generated unit carries both
`RuntimeDirectory=` and `LoadCredentialEncrypted=`.

Rejected: a one-shot **credential broker** (`filen-auth.service`,
`Type=oneshot`, `RemainAfterExit=yes`, `LoadCredentialEncrypted=filen-auth`)
that would stage the decrypted credential into `%t/filen/auth`, with the mount
and status units reading that file and never using `LoadCredentialEncrypted`
themselves. It works around the collision by moving the credential off the
per-unit mechanism, but it widens the exposure window: the decrypted credential
would sit in a stable `%t/filen/auth` path for the whole session instead of
living only in the unit's private `%d` credentials directory, and it adds a
second unit whose failure modes the panel must reason about. The `mkdir` in
`ExecStartPre` is a one-line, already-verified fix, so we prefer it.
