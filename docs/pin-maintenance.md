# Dependency-pin maintenance

`io.github.catalingb.filen` pins the two runtimes it downloads and runs them exactly as
pinned. This is the runbook for moving a pin safely. It exists because the
`filen` CLI is a public beta and, at the time of writing, the pin is a
**pre-release** chosen to dodge a crash.

## Why the pin is what it is

`filen` **0.2.8** (the latest *stable* release) **panics on `filen mount`**: after
resolving rclone it hits `Option::unwrap()` on `None` in
`pipe_output_to_logs` (`filen-rclone-wrapper/src/rclone_installation.rs`) and
aborts before mounting. The plugin therefore pins **0.2.9**, the release that
fixes it, even though GitHub marks 0.2.9 `"prerelease": true`. The full
reproduction is in
[upstream-filen-rs-0.2.8-mount-panic.md](upstream-filen-rs-0.2.8-mount-panic.md).

Because a pre-release is not served by `/releases/latest`, `bin/setup` fetches
the pinned tag directly (`releases/download/${FILEN_VERSION}/…`) and reads the
checksum from the release asset's `digest` field (or `OMARCHY_FILEN_SHA256`).

## Where the pins live

| Pin | Value | Source of truth |
|---|---|---|
| `filen` version | `FILEN_VERSION="0.2.9"` | `bin/setup` |
| `filen` source repo | `FILEN_SOURCE_REPO="FilenCloudDienste/filen-rs"` | `bin/setup` (read only by the upstream-pin check) |
| rclone version | `RCLONE_VERSION="1.74.2"` | `bin/setup` |
| rclone checksums | `RCLONE_CHECKSUM_LINUX_AMD64` / `_ARM64` | `bin/setup` |
| `filen` checksum | release asset `digest` | GitHub API at install time |

The docs mirrors are listed in [release.md](release.md#keeping-the-pins-consistent);
update them in the same change.

## Bumping `filen`

1. **Find the release.** On
   `github.com/FilenCloudDienste/filen-cli-releases/releases`, pick the target
   tag. **Do not rely on `/releases/latest`** — a pre-release is not "latest".
   Read the release notes for the fix or feature you need.
2. **Confirm the assets.** They are `filen-cli-<version>-<arch>-unknown-linux-<libc>`
   for x86_64/aarch64 × gnu/musl. A missing asset for a supported arch blocks
   the bump.
3. **Get the checksum.** The release asset carries a `sha256:` digest, visible
   in the GitHub API:
   ```bash
   curl -fsSL \
     "https://api.github.com/repos/FilenCloudDienste/filen-cli-releases/releases/tags/<version>" \
     | python3 -c 'import json,sys; [print(a["name"], a.get("digest")) for a in json.load(sys.stdin)["assets"]]'
   ```
   `bin/setup` reads this automatically; there is no checksum to hand-edit for
   `filen`. If a release ever lacks a digest, the install prints a warning and
   skips verification — prefer a release that has one, or export
   `OMARCHY_FILEN_SHA256` for a verified manual install.
4. **Edit `bin/setup`:** set `FILEN_VERSION="<version>"`.
5. **Update the docs mirrors** ([release.md](release.md#keeping-the-pins-consistent)).
6. **Run the automated suite:**
   ```bash
   python3 -m unittest discover -s tests
   python3 -m unittest discover -s tests/integration
   node tests/model.test.js
   ```
   Asset-name and version tests fail loudly if the pin is inconsistent.
7. **Live smoke mount** on a real box:
   ```bash
   bin/setup update          # re-download the pin and regenerate units
   bin/setup doctor          # must print 'ok filen <version> (installed)' and end 'healthy'
   # optional full pass:
   tests/e2e/live.sh
   ```
   Confirm `~/Filen` mounts and a file round-trips. This is the check CI cannot
   do and the only defence against a repeat of the 0.2.8 panic.
8. **Commit** the `bin/setup` and docs changes together.

## Bumping rclone

rclone's version and checksums are **embedded** in `bin/setup` (copied from
filen-rs's own `rclone_installation.rs`), so a mismatch means the mount's rclone
is re-downloaded or rejected — neither is fatal, but the pre-seed silently stops
working.

The weekly upstream check does **not** compare against the newest rclone release:
it reads the rclone version the pinned `filen` vendors
(`FILEN_SOURCE_REPO` → `filen-rclone-wrapper/src/rclone_installation.rs` at tag
`filen-cli@v$FILEN_VERSION`) and flags the pin only when it disagrees with that.
A newer rclone release on its own is not actionable — rclone ships far more often
than filen-rs, and the plugin only ever runs the vendored build.

1. Check which rclone version the target `filen` release pins
   (`rclone_installation.rs` upstream). The plugin must pre-seed the **same**
   version, or `filen` ignores the seed and downloads its own.
2. Fetch the published `rclone-v<version>-linux-{amd64,arm64}.zip.sha256`.
3. Update `RCLONE_VERSION`, `RCLONE_CHECKSUM_LINUX_AMD64`, and
   `RCLONE_CHECKSUM_LINUX_ARM64` in `bin/setup`.
4. Repeat steps 5–8 from the `filen` bump.

## How `setup doctor` reports health

`bin/setup doctor` is the single health read-out and exits non-zero when
unhealthy, so it can gate scripts:

```
ok      filen 0.2.9 (installed)        # installed marker matches the pin
stale   filen pinned 0.2.9, installed 0.2.8   # marker disagrees → run 'setup update'
missing filen binary at …/bin/filen (run 'setup install')
ok      rclone seed rclone-v1.74.2-linux-amd64
missing rclone seed …                  # pre-seed absent → mount re-downloads
ok      unit omarchy-filen-mount.service
missing unit … (run 'setup install')
ok      credential present / missing credential (run 'setup provision')
mount   omarchy-filen-mount.service: active
doctor: healthy                        # or 'doctor: unhealthy' (exit 1)
```

A `stale` line is exactly the 0.2.8-panic case: the installed binary is older
than the pin. `bin/setup update` fixes it. `setup doctor` is the first command
to run after any bump and the acceptance check for this runbook.

## Rolling back

If a new pin misbehaves, revert `FILEN_VERSION` (and the docs) to the last known
good value, run `bin/setup update`, confirm `doctor: healthy`, and re-run the
live smoke mount. Record why in the changelog and link the upstream report.
