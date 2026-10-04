# TODO — remaining verification

The plugin's **code, automated tests, docs, and CI are complete**. The items
below can only be confirmed on a real desktop session or with your Filen account,
so they are left open on purpose. Everything else in
`.scratch/omarchy-filen/hardening/plan.md` is resolved.

- [ ] **H06 — mount at login.** Log out and back in; confirm `~/Filen` mounts and
  the panel shows *mounted* without any manual action.
  *(Statically verified: unit `enabled`, `graphical-session.target.wants` symlink
  present, `After=/PartOf=/WantedBy=graphical-session.target`.)*
- [ ] **H08 — offline behaviour.** Disconnect the network; confirm the panel keeps
  the last state and marks quota stale (`checkedAt` age) rather than showing
  *failed*; reconnect and confirm it recovers without manual action.
- [ ] **H10 — panel error states.** Reproduce *not-installed*, *needs-auth*, and
  *failed*; confirm each shows only the correct action.
  *(`needs-auth` and `mounted` already verified visually.)*
- [ ] **H11 — multi-monitor.** With two monitors, confirm one service instance
  polls once and both bar widgets agree.
- [ ] **H12 / H17 — panel actions.** Click **Install**, **Repair**, and
  **Check for updates**; confirm the terminal runs `bin/setup` and the panel
  settles afterwards.
- [ ] **H14 — full live E2E.** Run `tests/e2e/live.sh` on a clean Omarchy box
  end to end (it automates the deterministic steps and prompts once for the
  sign-in).
- [ ] **H16 — release.** After merge, tag `v0.1.0` and confirm
  `omarchy plugin update` on an installed copy.

Known, intentional limitations (not bugs) are recorded in
[`docs/supported-environments.md`](docs/supported-environments.md) and
[`docs/troubleshooting.md`](docs/troubleshooting.md): this is a **mount**, not a
sync client (no offline folder); **single account**; the pinned `filen-rs` 0.2.9
is a **pre-release**; no plan/subscription data.

# Open points / future extensions
- [ ] create a configuration view
- [ ] study what is required to publish the plugin in omarchy plugins
- [ ] check how to run a fresh omarchy instalation in Qemu or a VM
- [ ] add Mermaid diagrams for the end users but also for the contributors
- [ ] add contributors guideline
- [ ] add dependabot or something similar
- [ ] add test coverage metrics
