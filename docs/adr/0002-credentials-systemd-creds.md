# Store the Filen credential with systemd-creds, not the keyring

The obvious convenience path — let the `filen` CLI persist to the OS keyring —
is unsafe **on this distro**: Omarchy's keyring is passwordless and plaintext at
rest (SDDM's `pam_gnome_keyring -auth` hook is removed), and the CLI would store
the account's E2EE master/private keys in it. We instead provision a
systemd-encrypted credential (`systemd-creds encrypt --user`), decrypted
RAM-only per unit and bound to TPM2 + uid + machine-id. Rejected: the keyring
(plaintext master keys), a plaintext auth-config file, and env vars (inherited
by children, visible in `/proc/<pid>/environ`).
