# TODO — remaining verification

The plugin's **code, automated tests, docs, and CI are complete**, and the
"future extensions" below are now done. What remains can only be confirmed on a
real desktop session or with your Filen account, so those items are left open on
purpose. Everything else in `.scratch/omarchy-filen/hardening/plan.md` is
resolved; the release/marketplace work lives in
`.scratch/omarchy-filen-release/`.

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
- [x] **H16 — release.** Tagged **`v0.2.0`** and pushed (`main` + tag).
  *(Not yet confirmed: `omarchy plugin update` — the local install is a manual
  dev copy, so the update path needs an install made with `omarchy plugin add`.)*

Known, intentional limitations (not bugs) are recorded in
[`docs/supported-environments.md`](docs/supported-environments.md) and
[`docs/troubleshooting.md`](docs/troubleshooting.md): this is a **mount**, not a
sync client (no offline folder); **single account**; the pinned `filen-rs` 0.2.9
is a **pre-release**; no plan/subscription data.

# Open points / future extensions

- [x] create a configuration view — a separate settings window (cogwheel in the
      panel); the recents list can be hidden with **Show recent files**.
- [x] study what is required to publish the plugin in omarchy plugins — no
      registry; a marketplace listing (`plugins.omarchy.org`) exists and a
      submission packet is ready (deliberately not filed yet).
- [x] check how to run a fresh omarchy installation in Qemu or a VM —
      [`docs/vm-testing.md`](docs/vm-testing.md) + `scripts/omarchy-filen-vm.sh`.
- [x] add Mermaid diagrams for the end users but also for the contributors —
      [`docs/architecture.md`](docs/architecture.md) plus a README lifecycle
      diagram.
- [x] add contributors guideline — [`CONTRIBUTING.md`](CONTRIBUTING.md).
- [x] add dependabot or something similar — Dependabot plus a weekly
      upstream-pin workflow.
- [x] add test coverage metrics — `coverage.py` over `bin/status` (~93%),
      reported in CI.
- [ ] establish some stability / performance tests.
