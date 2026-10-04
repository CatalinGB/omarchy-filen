# Build a Filen-specific plugin on the filen-rs CLI, not a generic mounter

Filen can be mounted today through `omarchy-cloud-plugin`/rclone (rclone has a
Filen backend since 1.73), so we had to justify rebuilding. We rejected the
rclone route: its Filen backend **requires the Filen CLI anyway**
(`filen export-api-key`), then duplicates credentials into `rclone.conf`, and
gives no Filen-native awareness (no recents, trash, favorites, notes, public
links, plan). We build a `filen.storage` plugin driving the **filen-rs CLI**,
differentiating on the Filen-native surface. Also rejected: linking
`filen-sdk-rs` (AGPL-3.0, unpublished, "partial implementation"), and forking
filen-rs to add `sync`/`login`.
