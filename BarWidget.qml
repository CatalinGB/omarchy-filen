import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar pill for the Filen plugin.
//
// Follows the first-party pattern: the widget owns the button and lazily loads
// the panel, forwarding the open/close contract the bar's popout coordinator
// expects. All state comes from the plugin's service, so two monitors show the
// same thing without either of them polling.
BarWidget {
  id: root
  moduleName: "filen.storage"

  readonly property var filen: bar && bar.shell ? bar.shell.serviceFor("filen.storage") : null

  // The service already folds its flags through Model.stateFor; reading it here
  // keeps the widget free of any state derivation of its own. With no service
  // yet the empty string falls through to the stopped glyph below.
  readonly property string state: filen ? filen.state : ""
  readonly property bool showLabel: filen ? filen.showLabel === true : false

  readonly property color defaultForeground: bar ? bar.foreground : Color.foreground

  // One icon stands for the whole plugin, so it shows the worst state rather
  // than the most common one. Anything merely off stays dim instead of
  // shouting.
  readonly property color iconColor: {
    if (state === "failed") return Color.urgent
    if (state === "needs-auth") return Color.accent
    return defaultForeground
  }

  readonly property real iconOpacity: {
    if (state === "mounted" || state === "failed" || state === "needs-auth") return 1.0
    if (state === "mounting") return 0.75
    return 0.55
  }

  readonly property string glyph: Model.stateGlyph(state)

  // A short next-to-icon label: usage while mounted, otherwise the state name.
  readonly property string labelText: {
    if (!filen) return ""
    if (state === "mounted" && filen.quotaKnown) return Model.formatBytes(filen.usedBytes)
    return Model.stateLabel(state)
  }

  // The shell injects `settings` into widgets but not into services, so the
  // widget forwards them. Every bar instance writes the same value, which is
  // harmless -- they all read the same shell.json entry.
  function syncService() {
    if (root.filen && "settings" in root.filen) root.filen.settings = root.settings
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if ("filen" in target) target.filen = root.filen
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  // Shape contract for shell summon/hide/toggle routing: the bar identifies a
  // panel by the widget mounted in its slot, so open/close/opened have to live
  // on this root rather than on the nested panel.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  // Forwarded so this widget can stand in for the panel as the bar's popout
  // identity: Bar.requestPopout prefers closeForPopoutSwitch over close, and
  // KeyboardPanel reads popoutSwitchClosing back off its owner.
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: { injectPanel(); syncService() }
  onFilenChanged: { injectPanel(); syncService() }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.showLabel && root.labelText !== "" ? root.glyph + "  " + root.labelText : root.glyph
    foreground: root.iconColor
    opacity: root.iconOpacity
    slotSize: Style.bar.statusSlot
    tooltipText: ""

    onPressed: function(b) {
      if (b === Qt.MiddleButton && root.filen) root.filen.refresh()
      else root.togglePanel()
    }
  }
}
