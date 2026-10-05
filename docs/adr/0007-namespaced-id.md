# Rename the plugin id to a namespaced `io.github.catalingb.filen`

The plugin shipped as `filen.storage`. The Omarchy marketplace requires a
globally unique, **permanent** plugin id and prefers a namespaced lowercase form
(`io.github.<user>.<name>`); the `omarchy.*` namespace is reserved for first
party. Ids cannot be reused once retired, so the rename had to happen **before**
the first submission.

We renamed to `io.github.catalingb.filen` across the manifest, the QML
(`moduleName`, `ipcTarget`, `serviceFor`), `bin/setup` (`PLUGIN_ID` and the
ownership marker), the docs, and the tests. The credential, the generated unit
names (`omarchy-filen-mount.service`, `filen-status.*`), `settings.conf`, and the
runtime dir are all keyed independently of the plugin id, so a live mount
survives the swap; the migration for an earlier install is remove-and-re-add,
because `omarchy plugin update` cannot cross an id rename.

Rejected: keeping `filen.storage` (not namespaced, collision-prone, not what the
marketplace prefers) or shortening to `filen` (no namespace).
