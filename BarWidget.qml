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
//
// `BarIconButton` is a fixed-width slot, so the optional text label is a
// sibling of the icon rather than baked into its `text`: the widget sizes
// itself to the two together and reserves exactly that width in the bar
// (otherwise the label overlaps the neighbouring widget).
BarWidget {
  id: root
  moduleName: "io.github.catalingb.filen"

  readonly property var filen: bar && bar.shell ? bar.shell.serviceFor("io.github.catalingb.filen") : null

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
    var tone = Model.stateTone(state)
    if (tone === "urgent") return Color.urgent
    if (tone === "accent") return Color.accent
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

  readonly property bool labelShown: root.showLabel && root.labelText !== ""

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

  // Size to the icon plus the optional label; the bar reserves this width.
  implicitWidth: row.implicitWidth
  implicitHeight: row.implicitHeight

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

  Row {
    id: row
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    // Only pay the gap when the label is actually shown.
    spacing: root.labelShown ? Style.space(5) : 0

    BarIconButton {
      id: button
      bar: root.bar
      text: root.glyph
      foreground: root.iconColor
      opacity: root.iconOpacity
      slotSize: Style.bar.statusSlot
      tooltipText: ""
      // The overlay below owns input, so icon and label behave as one target.
      interactive: false
    }

    Text {
      id: labelTextItem
      visible: root.labelShown
      height: button.height
      text: root.labelText
      color: root.iconColor
      opacity: root.iconOpacity
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
      verticalAlignment: Text.AlignVCenter
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.MiddleButton

    onPressed: function(mouse) {
      if (mouse.button === Qt.MiddleButton && root.filen) root.filen.refresh()
      else root.togglePanel()
    }
  }
}
