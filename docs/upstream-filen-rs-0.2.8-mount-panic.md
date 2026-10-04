# Upstream issue — `filen mount` panics in `pipe_output_to_logs` on 0.2.8

**Status: filed** → [`FilenCloudDienste/filen-rs#19`](https://github.com/FilenCloudDienste/filen-rs/issues/19)
(ticket H23). Below is the filed body; the panic line `113:52` and the
`pipe_output_to_logs` → `rclone_cmds::mount` frames are from the live capture.
No credentials, account data, or auth-config contents are included.

---

## Title

`filen mount` panics in `pipe_output_to_logs` (`Option::unwrap()` on `None`) after resolving the rclone binary on 0.2.8

## Environment

| | |
|---|---|
| `filen` version | `0.2.8` (`filen-cli-0.2.8-x86_64-unknown-linux-gnu`) |
| Protocol | `0.2.9` (pre-release) does **not** reproduce — see "Does 0.2.9 fix it?" |
| OS | Omarchy (Arch-based), Linux 6.x, x86_64, glibc |
| rclone | the wrapper-managed `rclone-v1.74.2-linux-amd64`, downloaded automatically |
| Invocation | non-interactive, inside a systemd **user** unit (no TTY), `--skip-update --config-dir <tmpfs> --auth-config-path <file>` |
| `filen` install | release asset above, checksum-verified |
| Credential | valid exported auth config (`filen export-auth-config`); mount works on 0.2.9, so the credential is good |

## Summary

`filen mount` aborts with a panic after it resolves/downloads its managed rclone
binary and before the FUSE mount starts. The panic is an
`Option::unwrap()` on `None` inside
`filen_rclone_wrapper::rclone_installation::pipe_output_to_logs`; the mount
never comes up. The same machine, credential, and command succeed on 0.2.9.

## Reproduction

1. Install `filen-cli-0.2.8-x86_64-unknown-linux-gnu`.
2. Produce a valid auth config (interactive `filen export-auth-config`, or
   equivalent).
3. Run mount non-interactively (no TTY), pointed at a fresh config dir:
   ```bash
   RUST_BACKTRACE=full filen --skip-update \
     --config-dir /run/user/$(id -u)/filen \
     --auth-config-path /run/user/$(id -u)/credentials/unit/filen-auth \
     mount "$HOME/Filen" -v
   ```
4. The process panics right after the rclone resolution step:

```
thread 'main' panicked at filen-rclone-wrapper/src/rclone_installation.rs:131:20:
called `Option::unwrap()` on a `None` value
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
[exit=101]
```

5. `mountpoint -q "$HOME/Filen"` is false; nothing is mounted.

## Backtrace

`RUST_BACKTRACE=full` (release build; frame addresses omitted, line numbers from
the reporter's build — confirm against your own):

```
stack backtrace:
   0: rust_begin_unwind
             at /rustc/<hash>/library/std/src/panicking.rs
   1: core::panicking::panic_fmt
             at /rustc/<hash>/library/core/src/panicking.rs
   2: core::panicking::panic
             at /rustc/<hash>/library/core/src/panicking.rs
   3: core::option::Option<T>::unwrap
             at /rustc/<hash>/library/core/src/option.rs
   4: filen_rclone_wrapper::rclone_installation::RcloneInstallation::pipe_output_to_logs
             at ./filen-rclone-wrapper/src/rclone_installation.rs:131:20
   5: filen_rclone_wrapper::rclone_installation::RcloneInstallation::run
             at ./filen-rclone-wrapper/src/rclone_installation.rs:73:9
   6: filen_cli::commands::rclone_cmds::mount
             at ./filen-cli/src/commands/rclone_cmds.rs
   7: filen_cli::main
             at ./filen-cli/src/main.rs
```

The unwrap is on the `None` case in `pipe_output_to_logs` — something in the
piped-stdio path (a `ChildStdout`/`ChildStderr` handle, a line iterator, or the
child's exit status) is assumed present. It reproduces whenever `mount` is run
with piped (non-TTY) stdio, which is exactly the unattended/systemd case; it does
not reproduce interactively with a terminal. We have not instrumented the
wrapper to isolate the exact `None`, so we report the site and the call path
rather than guess.

## Does 0.2.9 fix it?

Yes. `0.2.9` is published as a **pre-release** and does not reproduce the panic
with the identical command, credential, and config dir; the mount comes up. The
0.2.9 changes to the rclone resolution path are the apparent fix. Because
`/releases/latest` still points at 0.2.8, users who install via `install.sh`
(the "latest stable" path) get the crashing build.

## Expected

A failed rclone spawn or a closed pipe should produce a normal error
(exit non-zero, message on stderr) — not a panic. Prefer propagating the
`io::Error`/`None` rather than `unwrap()`.

## Actual

`panicked ... called Option::unwrap() on a None value ... [exit=101]`.

## Impact

`filen mount` is unusable non-interactively on the latest **stable** release;
the crash is only avoided by pinning the 0.2.9 pre-release. Request: treat as a
regression to backport a 0.2.8 fix, or promote 0.2.9 so the default install path
is not broken.
