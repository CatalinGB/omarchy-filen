# Run the mount's config dir on tmpfs, accepting an ephemeral cache

`filen mount` writes `rclone.conf` — containing the master keys, private key, and
API key — and the VFS file cache under a single `--config-dir`, and that cache
path cannot be redirected (`filen mount`'s trailing `rclone_args` reject hyphen
flags). To avoid persisting the keys, the config dir is a systemd
`RuntimeDirectory` (tmpfs). The consequence is deliberate: the VFS cache is
RAM-only and does not survive reboot, so previously-opened files are not offline
across restarts, and the cache is capped with `--cache-size` so RAM cannot
balloon. Rejected: a persistent config dir, which would leave plaintext keys on
disk.
