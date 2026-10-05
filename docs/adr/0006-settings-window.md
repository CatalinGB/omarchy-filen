# Configure Filen from a separate settings window, not the panel body

The panel is a narrow, scrollable popup anchored to a bar slot. The first cut
put the settings inline at the bottom of that popup; the owner could not find
them and they scrolled out of view. We moved configuration to a **separate
window**: a `PanelWindow` layer-shell overlay (a dimmed scrim with a centered
card), owned by the QML service singleton (`SettingsWindow.qml`) and opened from
a cogwheel in the panel's hero.

Rejected: (a) the inline section — undiscoverable and cramped; (b) an ordinary
top-level window — the tiler places it, so it lands beside other windows unless
a Hyprland rule floats it; (c) a bespoke editor built on the shell's schema
dialog — the installed shell (4.0.0.alpha) renders no schema-driven dialog at
all, so there was nothing to reuse.

The window persists edits through `shell.updateEntryInline` on the plugin's own
`shell.json` entry; the service mirrors the mount-affecting keys to
`settings.conf` for the systemd units (see ADR-0003 and ADR-0004). Owning the
window in the service rather than the bar widget keeps it working whenever the
plugin is enabled, independent of the widget's bar placement.
