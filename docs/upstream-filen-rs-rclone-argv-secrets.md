# Upstream issue (draft) — `filen`/rclone expose secrets on the command line

**Status: draft, not filed.** This documents an upstream `filen-rs` weakness
the plugin cannot fix in its own code; it is the follow-up to the marketplace
security review. Do not file without the owner's go-ahead. No credentials or
account data are included.

Source reviewed: [`FilenCloudDienste/filen-rs`](https://github.com/FilenCloudDienste/filen-rs),
`filen-rclone-wrapper/src/rclone_installation.rs` at tag `filen-cli@v0.2.9`
(the pinned build). Line numbers are from that tag.

---

## Title

`filen mount` passes the rclone RC password (and the Filen API key) as process
arguments, readable by other local users via `/proc/<pid>/cmdline`

## Environment

| | |
|---|---|
| `filen` version | `0.2.9` (also present in `0.2.8`) |
| OS | Omarchy (Arch-based), Linux 6.x, x86_64, glibc |
| Invocation | non-interactive, inside a systemd **user** unit |
| `/proc` | default mount options — **no `hidepid`** |

## Summary

Two command lines carry secrets:

1. **rclone RC password (mount lifetime).** `execute_in_background` passes the
   randomly generated RC password as `--rc-pass <password>` and the RC endpoint
   as `--rc-addr 127.0.0.1:<port>`
   (`rclone_installation.rs:108-113`). The `rclone` child runs for the whole
   mount. On a host where `/proc/<pid>/cmdline` is world-readable, any other
   local user can read the password and the port and then authenticate to the
   RC API (bound to loopback) to list or copy the mounted account's files. The
   debug log even acknowledges the sensitivity — it prints `--rc-pass (omitted)`
   — but the real argv still contains it.

2. **Filen API key (brief).** `obscure_password_for_rclone`
   (`rclone_installation.rs:341-350`) runs `rclone obscure <api_key>`, so the
   account's API key appears in that child's argv until it exits.

## Reproduction

While a `filen` mount is running:

```bash
pid=$(pgrep -f 'rclone.*--rc-pass' | head -1)
cat /proc/$pid/cmdline | tr '\0' ' '
# ... --rc --rc-user filen-rclone-wrapper --rc-pass <40-hex> --rc-addr 127.0.0.1:<port> ...
```

The file is mode `-r--r--r--` (world-readable) on a default `/proc`.

## Expected

Secrets should not be passed as arguments. Options:

- The RC password and user via the environment (`RCLONE_RC_PASS`,
  `RCLONE_RC_USER`) or a config file, not `--rc-*` flags. (`/proc/<pid>/environ`
  is owner-only, unlike `cmdline`.)
- `rclone obscure` reading the password from **stdin** instead of an argument.

## Actual

`--rc-pass <secret>` and `obscure <api_key>` appear in world-readable process
arguments.

## Impact

On a single-user desktop the exposure is within the same trust boundary the
user already holds (they can read the mount directly). On a machine with more
than one local user — or any process running as another user — it is a
confidentiality/integrity escalation: the RC password grants access to the
mounted Filen files for the life of the mount.

## Plugin-side mitigation

The plugin does not control the `filen`→`rclone` command line, so it cannot
remove the arguments. It documents the risk and recommends mounting `/proc`
with `hidepid=2` (see [SECURITY.md](../SECURITY.md)); it is also pinning a fixed
`filen` release once upstream ships one.
