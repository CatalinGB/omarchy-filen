# Security model — `filen.storage`

This document states what the plugin protects, what it does **not**, and why. It
is written for the user and for a reviewer. It reflects the decisions in
`.scratch/omarchy-filen/` (tickets 02 and 11, and the research file
`research/keyring-no-knowledge.md`).

## The one-paragraph version

The plugin **layer never touches your Filen keys**. Authentication is performed
by the filen-rs `filen` CLI inside short-lived or supervised **systemd user
units** that receive your credential through a **systemd-encrypted** blob. The
blob is bound to this machine's TPM2/host key **and** your user/machine-id; it is
decrypted only into a per-unit RAM directory while a unit runs, and removed when
it stops. Nothing the plugin itself reads or renders contains a secret. This is
stronger than the Omarchy keyring, which on this distro is passwordless and
**plaintext at rest**.

## Why not the system keyring

Measured on Omarchy (see the research file):

- `default-keyring.sh` creates a **passwordless** keyring, and its file is
  **readable plaintext** — the researcher read a real GitHub token from it.
- SDDM's `pam_gnome_keyring -auth` unlock hook is deliberately removed.
- The `filen` CLI stores its SDK auth config (master keys, private key, API key)
  in that keyring. "Use the keyring" therefore writes your **decryption keys**
  to a plaintext file.

So the keyring is not a way to keep secrets off disk here; it *is* disk.

## What is protected

| Asset | Protection |
|---|---|
| Filen master keys / private key / API key | Never in the plugin; only inside the `filen`/rclone process or the systemd credential |
| Persistent credential copy | AES-256-GCM, bound to TPM2 + host key + uid + machine-id (`~/.config/credstore.encrypted/filen-auth`) |
| Plaintext credential | Exists only in `/run/user/<uid>/credentials/<unit>/` (0400), removed when the unit stops |
| `rclone.conf` (contains the same keys) | Written under a **tmpfs** `--config-dir`, never on persistent disk |
| Plugin source (QML, helper) | Reads no secret; holds no credential |

## What is **not** protected (residual risks)

Stated plainly so no one over-trusts the design:

1. **Same-UID processes.** The credential file is checked by UID, not per-app.
   While a unit runs, any process running as you can read the decrypted
   credential. systemd credentials are not per-application isolation.
2. **Root.** Root can decrypt the blob (via the TPM or
   `/var/lib/systemd/credential.secret`). This is true of any userspace design.
3. **RAM and swap.** The plaintext lives in RAM while the mount runs. systemd
   classifies **user-unit** credentials `weak` (swappable). On this box `/`, the
   swapfile, and zram mitigate it — but the guarantee is disk encryption, not the
   design.
4. **Process memory.** `filen` and its child `rclone` hold the keys in memory for
   the mount's lifetime; readable via ptrace/core dumps by the same UID.
5. **The mount is plaintext at the FUSE boundary.** Files are decrypted in the
   kernel/user space of the mounter. Anyone who can read `~/Filen` as you can
   read your files — that is the point of a mount.
6. **Cold-boot / DMA / compromised session** — out of scope for any userspace
   design.

In short: **"no-knowledge" is about the plugin layer, not about eliminating the
secret.** The plugin owns no credential; the secret still exists as ciphertext at
rest and plaintext in RAM while mounted.

## Credential lifecycle

- **Provision (once):** `filen export-auth-config` (interactive email/password/
  2FA) → `systemd-creds encrypt --user --name=filen-auth` → `shred` the
  plaintext. The blob lands in `~/.config/credstore.encrypted/`.
- **Use:** each unit decrypts the blob into its RAM credentials dir at start;
  the mount unit holds it for the session, the status timer only for its brief
  run.
- **Rotate:** a Filen password change (or a new machine) invalidates the blob —
  re-run the setup script. `filen`'s own docs confirm a password change requires
  re-exported credentials.
- **Remove:** the credential blob is deleted only by an explicit
  `uninstall --purge`; a normal uninstall leaves it.

## Why the mount writes keys to disk — and why they're in tmpfs

`filen mount` (rclone-backed) constructs an `rclone.conf` containing the master
keys, private key, and API key. There is no rclone mechanism to fetch these from
a keyring at runtime. The plugin therefore points `--config-dir` at a systemd
`RuntimeDirectory` (tmpfs), so that file never touches persistent media. The cost
is that the VFS file cache lives in RAM and does not survive reboot; the cache
size is capped (`--cache-size`) so RAM cannot balloon.

## Hard requirement

The design needs **systemd ≥ 250** (`LoadCredential=`) and **≥ 256** for
`systemd-creds encrypt --user`. Omarchy ships 261. On older systems the
credential mechanism is unavailable and the design must be reworked (the keyring
or a plaintext file would be the only options — both rejected).

## Reporting

Found a flaw? Open an issue on the plugin repository. Please do not include real
credentials or account data in a report.
