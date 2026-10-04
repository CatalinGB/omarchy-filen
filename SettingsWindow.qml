import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// The plugin's full configuration surface: a separate dialogue shown over a
// scrim, opened from the panel's cogwheel. It is owned by Service.qml (which
// loads it on first use and injects itself as `service`), so every edit goes
// through the same persistence path the panel uses.
Item {
  id: root

  // Injected by Service.qml's Loader.
  property var service: null

  readonly property bool shown: window.visible
  readonly property bool ready: service !== null && service !== undefined

  // Which screen to open on (the focused one); chosen at open, not bound, so
  // the window does not hop monitors while it is being read.
  property var openedOn: null

  function focusedScreen() {
    var monitor = Hyprland.focusedMonitor
    var name = monitor ? String(monitor.name || "") : ""
    if (name === "") return null
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (String(screens[i].name) === name) return screens[i]
    return null
  }

  function show() { openedOn = focusedScreen(); window.visible = true }
  function hide() { window.visible = false }

  readonly property color foreground: Color.foreground
  readonly property color background: Qt.rgba(Color.popups.background.r, Color.popups.background.g, Color.popups.background.b, 1)
  readonly property string fontFamily: Style.font.family
  readonly property color hairline: Util.alpha(foreground, 0.16)

  function setting(name, fallback) {
    return root.ready ? root.service.setting(name, fallback) : fallback
  }
  function persist(values) {
    if (root.ready) root.service.persistSettings(values)
  }
  function mountAtLogin() {
    return root.ready && root.service.autoMount === true
  }

  PanelWindow {
    id: window
    visible: false
    screen: root.openedOn !== null ? root.openedOn : null
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "filen-settings"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    // Dim what is behind and give click-outside-to-close somewhere to live.
    Rectangle {
      anchors.fill: parent
      color: Qt.rgba(0, 0, 0, 0.45)
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.hide()
    }

    FocusScope {
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.hide()
    }

    BorderSurface {
      id: card
      anchors.centerIn: parent
      width: Math.min(parent.width - Style.space(48), Style.space(460))
      height: Math.min(content.implicitHeight + card.contentTopInset + card.contentBottomInset,
                       parent.height - Style.space(48))
      color: root.background
      borderSpec: Border.flat(root.hairline, Style.normalBorderWidth)
      radius: Style.cornerRadius
      padding: Style.space(18)

      // A click on the card stays on the card.
      MouseArea { anchors.fill: parent }

      Flickable {
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: content
          width: parent.width
          spacing: Style.space(12)

          // ---- header ----
          RowLayout {
            width: parent.width
            spacing: Style.space(8)

            Text {
              textFormat: Text.PlainText
              Layout.fillWidth: true
              text: "Filen settings"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }

            PanelActionButton {
              iconText: "󰅖"
              tooltipText: "Close"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.hide()
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ---- storage ----
          PanelSectionHeader {
            text: "STORAGE"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          SettingTextRow {
            label: "Mount folder"
            value: root.setting("mountRoot", "~/Filen")
            onCommitted: function(v) { root.persist({ mountRoot: v }) }
          }

          SettingNumberRow {
            label: "Cache limit"
            suffix: "GB"
            value: root.setting("cacheMaxSizeGB", 4)
            from: 1
            to: 512
            stepSize: 1
            onCommitted: function(v) { root.persist({ cacheMaxSizeGB: v }) }
          }

          PanelSeparator { foreground: root.foreground }

          // ---- refresh ----
          PanelSectionHeader {
            text: "REFRESH"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          SettingNumberRow {
            label: "Status refresh"
            suffix: "s"
            value: root.setting("refreshIntervalSec", 15)
            from: 5
            to: 300
            stepSize: 5
            onCommitted: function(v) { root.persist({ refreshIntervalSec: v }) }
          }

          SettingNumberRow {
            label: "Storage refresh"
            suffix: "min"
            value: root.setting("apiRefreshMin", 10)
            from: 5
            to: 240
            stepSize: 5
            onCommitted: function(v) { root.persist({ apiRefreshMin: v }) }
          }

          PanelSeparator { foreground: root.foreground }

          // ---- panel ----
          PanelSectionHeader {
            text: "PANEL"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Toggle {
            width: parent.width
            label: "Show text in bar"
            description: "Print the mount state next to the bar icon."
            checked: root.setting("showLabel", false) === true
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.persist({ showLabel: !checked })
          }

          Toggle {
            width: parent.width
            label: "Show recent files"
            description: "List recently changed files in the panel. Turn off if you mainly use Filen for backup."
            checked: root.setting("showRecents", true) === true
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.persist({ showRecents: !checked })
          }

          Toggle {
            width: parent.width
            label: "Mount at login"
            description: "Start the Filen mount when you sign in."
            checked: root.mountAtLogin()
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: if (root.ready) root.service.setAutoMount(!checked)
          }

          PanelSeparator { foreground: root.foreground }

          // ---- reset ----
          BorderSurface {
            id: resetRow
            width: parent.width
            implicitHeight: resetLabel.implicitHeight + Style.space(20)
            height: implicitHeight
            color: resetMouse.containsMouse ? Util.alpha(root.foreground, 0.06) : "transparent"
            borderSpec: Border.flat(root.hairline, Style.normalBorderWidth)
            radius: Style.cornerRadius

            MouseArea {
              id: resetMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.persist({
                mountRoot: "~/Filen",
                cacheMaxSizeGB: 4,
                refreshIntervalSec: 15,
                apiRefreshMin: 10,
                showLabel: false,
                showRecents: true
              })
            }

            Text {
              id: resetLabel
              textFormat: Text.PlainText
              anchors.centerIn: parent
              text: "Reset to defaults"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            text: "Changes save immediately."
            color: Util.alpha(root.foreground, 0.5)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }
        }
      }
    }
  }

  // ---------------------------------------------------------------- rows

  component SettingTextRow: RowLayout {
    id: settingTextRow
    property string label: ""
    property string value: ""
    signal committed(string value)

    width: parent ? parent.width : implicitWidth
    spacing: Style.space(8)

    Text {
      textFormat: Text.PlainText
      text: settingTextRow.label
      color: Util.alpha(root.foreground, 0.6)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Layout.alignment: Qt.AlignVCenter
    }

    Item { Layout.fillWidth: true }

    TextField {
      id: settingTextInput
      Layout.preferredWidth: Style.space(200)
      text: settingTextRow.value
      horizontalAlignment: Text.AlignRight
      foreground: root.foreground
      accent: Color.accent
      onEditingFinished: {
        var next = String(text).trim()
        if (next === "" || next === settingTextRow.value) {
          text = settingTextRow.value
          return
        }
        settingTextRow.committed(next)
      }
    }
  }

  component SettingNumberRow: RowLayout {
    id: settingNumberRow
    property string label: ""
    property string suffix: ""
    property int value: 0
    property int from: 0
    property int to: 100
    property int stepSize: 1
    signal committed(int value)

    width: parent ? parent.width : implicitWidth
    spacing: Style.space(8)

    Text {
      textFormat: Text.PlainText
      text: settingNumberRow.label
      color: Util.alpha(root.foreground, 0.6)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Layout.alignment: Qt.AlignVCenter
    }

    Item { Layout.fillWidth: true }

    NumberField {
      id: settingNumberField
      label: ""
      value: settingNumberRow.value
      from: settingNumberRow.from
      to: settingNumberRow.to
      stepSize: settingNumberRow.stepSize
      foreground: root.foreground
      fieldWidth: Style.space(120)
      Layout.alignment: Qt.AlignVCenter
      onModified: function(v) { settingNumberRow.committed(v) }
    }

    Text {
      visible: settingNumberRow.suffix !== ""
      text: settingNumberRow.suffix
      color: Util.alpha(root.foreground, 0.6)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Layout.alignment: Qt.AlignVCenter
    }
  }
}
