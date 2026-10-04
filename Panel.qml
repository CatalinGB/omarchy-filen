import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The Filen panel: mount state, storage usage, recent files, and the one
// action each condition actually wants.
//
// Credential-free by construction. Everything shown comes from the plugin's
// service (which reads the non-secret status document), and every action is
// either a `systemctl --user` control the service owns or a terminal running
// bin/setup. The panel never runs `filen` and never touches the credential.
//
// Loaded by BarWidget, which injects `bar`, `settings`, `anchorItem`,
// `hostWidget` and the `filen` service. `manageIpc` is off because this panel
// exposes a richer IPC surface (refresh/status) than the base provides.
Panel {
  id: root
  moduleName: "filen.storage"
  ipcTarget: "filen.storage"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var filen: null

  // The bar tracks the widget in its slot, not this nested panel, so anything
  // the popout coordinator compares against has to be the widget.
  readonly property var barIdentity: hostWidget || root

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---------------------------------------------------------------- state

  readonly property bool hasService: filen !== null && filen !== undefined
  readonly property string state: hasService ? String(filen.state || "stopped") : "failed"
  readonly property string unitState: hasService ? String(filen.unitState || "") : ""
  readonly property bool installed: hasService && filen.installed === true
  readonly property bool authenticated: hasService && filen.authenticated === true
  readonly property bool running: hasService && filen.running === true
  readonly property bool busy: hasService && filen.busy === true
  readonly property var remoteFiles: hasService && Array.isArray(filen.files) ? filen.files : []

  // The service owns the staleness rule (derived there from apiRefreshMin), so
  // the panel reads one value rather than re-deriving it. `nowMs` is refreshed
  // on a panel timer so the displayed age is live, not frozen at open time.
  readonly property real staleAfterSec: hasService ? Number(filen.staleAfterSec || 1200) : 1200
  property double nowMs: Date.now()

  readonly property bool storageStale: {
    if (!hasService || !filen.quotaKnown) return true
    if (!filen.checkedAt || filen.checkedAt <= 0) return true
    return (root.nowMs / 1000 - filen.checkedAt) > root.staleAfterSec
  }
  readonly property string usageValue: {
    // Without a known quota, Model.usageText would render "0 B", which reads
    // like an empty drive. Say "unknown" instead.
    if (!hasService || !filen.quotaKnown) return "—"
    var text = Model.usageText(filen)
    return text !== "" ? text : "—"
  }
  readonly property real usageFraction: hasService ? Model.usageFraction(filen) : 0

  // Which actions the current state offers. The rule set lives in Model.js so
  // it is one source of truth (and unit-testable); the panel only binds rows to
  // it. See panelActions: not-installed -> Install; signed out -> Set up;
  // stopped -> Mount; unit failed -> Repair; mounted -> Unmount + recents. A
  // signed-out or failed unit never offers Mount (H10).
  readonly property var actions: hasService
    ? Model.panelActions({
        ok: filen.ok,
        installed: root.installed,
        authenticated: root.authenticated,
        running: root.running,
        unitState: root.unitState
      })
    : Model.noActions()

  readonly property bool mountVisible: root.actions.mount
  readonly property bool filesVisible: root.actions.files && remoteFiles.length > 0
  readonly property bool setupVisible: root.actions.setup
  readonly property bool installVisible: root.actions.install
  readonly property bool repairVisible: root.actions.repair
  readonly property bool updateVisible: root.actions.updates
  readonly property bool autoLoginVisible: root.actions.autoLogin
  readonly property bool journalHintVisible: root.actions.journalHint

  readonly property string mountLabel: running ? "Unmount Filen" : "Mount Filen"
  readonly property string mountSubtitle: running
    ? String(filen.mountPath || "")
    : "Start the FUSE mount as a systemd user service"
  readonly property string setupLabel: authenticated ? "Re-provision Filen" : "Set up Filen"
  readonly property string setupSubtitle: authenticated
    ? "Sign in again and refresh the encrypted credential"
    : "Sign in once and store the credential systemd-encrypted"
  readonly property color stateColor: {
    if (state === "failed") return root.urgent
    if (state === "needs-auth") return Color.accent
    return root.foreground
  }

  // The toggle reads the service's autoMount, with a short-lived optimistic
  // override so the switch responds on click; the override clears once the
  // service reports a new value.
  property var autoMountOverride: null
  readonly property bool autoMountOn: autoMountOverride === null
    ? (hasService && filen.autoMount === true)
    : autoMountOverride

  // ---------------------------------------------------------------- cursor

  // Keyboard cursor state. Declared (not left dynamic) so the change handlers
  // and the `root.focusSection`/`root.fileIndex`/`root.cursorActive` bindings
  // re-evaluate and highlight the focused row.
  property string focusSection: "mount"
  property int fileIndex: 0
  property bool cursorActive: false

  // Focusable rows in visual order, skipping whatever is hidden. Files are one
  // section with an inner index, mirroring the Dropbox panel.
  function sectionList() {
    var list = []
    if (mountVisible) list.push("mount")
    if (filesVisible) list.push("files")
    if (autoLoginVisible) list.push("autologin")
    if (setupVisible) list.push("setup")
    if (installVisible) list.push("install")
    if (repairVisible) list.push("repair")
    if (updateVisible) list.push("updates")
    return list
  }

  function ensureCursor() {
    var list = sectionList()
    if (list.indexOf(focusSection) < 0) focusSection = list.length > 0 ? list[0] : "mount"
    if (focusSection === "files") {
      if (remoteFiles.length === 0) focusSection = list.indexOf("mount") >= 0 ? "mount" : "autologin"
      else fileIndex = Math.max(0, Math.min(fileIndex, remoteFiles.length - 1))
    }
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    ensureCursor()
    if (dy === 0) return
    var list = sectionList()
    if (focusSection === "files") {
      if (dy > 0 && fileIndex < remoteFiles.length - 1) { fileIndex += 1; scrollCursorIntoView(); return }
      if (dy < 0 && fileIndex > 0) { fileIndex -= 1; scrollCursorIntoView(); return }
    }
    var at = list.indexOf(focusSection)
    if (at < 0) at = 0
    var next = Math.max(0, Math.min(list.length - 1, at + dy))
    focusSection = list[next]
    if (focusSection === "files") fileIndex = dy > 0 ? 0 : remoteFiles.length - 1
    scrollCursorIntoView()
  }

  function setSection(name) {
    cursorActive = true
    focusSection = name
  }

  function setFileCursor(index) {
    cursorActive = true
    focusSection = "files"
    fileIndex = Math.max(0, Math.min(index, remoteFiles.length - 1))
    scrollCursorIntoView()
  }

  function selectedFile() {
    if (remoteFiles.length === 0) return null
    return remoteFiles[Math.max(0, Math.min(fileIndex, remoteFiles.length - 1))]
  }

  function scrollItemIntoView(item) {
    if (!panelFlick || !item) return
    Qt.callLater(function() {
      if (!item) return
      var margin = Style.space(6)
      var point = item.mapToItem(panelFlick.contentItem, 0, 0)
      var top = point.y
      var bottom = top + item.height
      var viewTop = panelFlick.contentY
      var viewBottom = viewTop + panelFlick.height
      var maxY = Math.max(0, panelFlick.contentHeight - panelFlick.height)
      if (top < viewTop + margin) panelFlick.contentY = Math.max(0, top - margin)
      else if (bottom > viewBottom - margin) panelFlick.contentY = Math.min(maxY, bottom + margin - panelFlick.height)
    })
  }

  function cursorItem() {
    if (focusSection === "mount") return mountRow
    if (focusSection === "files" && fileColumn && fileIndex >= 0 && fileIndex < fileColumn.children.length) return fileColumn.children[fileIndex]
    if (focusSection === "autologin") return autoLoginRow
    if (focusSection === "setup") return setupRow
    if (focusSection === "install") return installRow
    if (focusSection === "repair") return repairRow
    if (focusSection === "updates") return updateRow
    return null
  }

  function scrollCursorIntoView() {
    scrollItemIntoView(cursorItem())
  }

  function activateCursor() {
    ensureCursor()
    if (focusSection === "mount") mountAction()
    else if (focusSection === "files") openFile(selectedFile())
    else if (focusSection === "autologin") toggleAutoMount()
    else if (focusSection === "setup") runSetup("provision")
    else if (focusSection === "install") runSetup("install")
    else if (focusSection === "repair") runSetup("install")
    else if (focusSection === "updates") runSetup("update")
  }

  // ---------------------------------------------------------------- actions

  function mountAction() {
    if (!hasService || busy) return
    filen.toggleMount()
  }

  function toggleAutoMount() {
    if (!hasService || busy) return
    autoMountOverride = !root.autoMountOn
    filen.setAutoMount(root.autoMountOn)
  }

  // Opens Nautilus at the file's parent; mirrors the cloud/dropbox reference.
  function openFile(file) {
    if (!file || !file.path) return
    close()
    Quickshell.execDetached(["uwsm-app", "--", "nautilus", Model.fileUri(String(file.path))])
  }

  // Interactive provisioning/installation must happen in a real terminal, so
  // close the panel (which holds exclusive keyboard focus) and hand the script
  // to the session's terminal launcher.
  function runSetup(args) {
    if (!hasService) return
    var command = Util.shellQuote(String(filen.setupScript || ""))
    if (args) command += " " + args
    close()
    Quickshell.execDetached([terminalLauncher, "bash", "-lc", command])
  }

  function refresh() {
    if (hasService) filen.refresh()
  }

  // The shell injects `settings` into widgets but not services. The widget is
  // expected to forward them, but the panel does too so showLabel /
  // refreshIntervalSec / apiRefreshMin are honoured even on a hot-reload.
  function syncService() {
    if (root.filen && "settings" in root.filen) root.filen.settings = root.settings
  }

  // ---------------------------------------------------------------- terminal

  // Prefer Omarchy's launcher (setsid + uwsm-app + the user's chosen
  // terminal); fall back to xdg-terminal-exec, which is always present.
  property string terminalLauncher: "xdg-terminal-exec"

  Process {
    id: terminalProbe
    running: true
    command: ["bash", "-lc",
      "if [ -x /usr/share/omarchy/bin/omarchy-launch-terminal ]; then " +
      "printf %s /usr/share/omarchy/bin/omarchy-launch-terminal; " +
      "elif command -v omarchy-launch-terminal >/dev/null 2>&1; then " +
      "command -v omarchy-launch-terminal; fi"]
    stdout: StdioCollector { id: terminalProbeOut; waitForEnd: true }
    onExited: {
      var found = String(terminalProbeOut.text || "").trim()
      if (found !== "") root.terminalLauncher = found
    }
  }

  // ---------------------------------------------------------------- lifecycle

  function handleOpened() {
    cursorActive = false
    fileIndex = 0
    nowMs = Date.now()
    syncService()
    if (panelFlick) panelFlick.contentY = 0
    refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function open() {
    root.controller.show()
    handleOpened()
  }

  function openFromHotkey() {
    root.open()
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  // Route panel switching through the widget, not this nested panel.
  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function")
      return bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  onFilenChanged: syncService()
  onSettingsChanged: syncService()
  onRemoteFilesChanged: ensureCursor()
  onFocusSectionChanged: scrollCursorIntoView()

  // A freshly polled autoMount supersedes the optimistic toggle value.
  Connections {
    target: root.filen
    function onAutoMountChanged() { root.autoMountOverride = null }
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { if (root.filen) root.filen.refresh(); return "ok" }
    function status(): string { return root.filen ? String(root.filen.statusText || "") : "" }
  }

  // ---------------------------------------------------------------- content

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var key = String(t).toLowerCase()
        if (key === "r") root.refresh()
        else if (key === "m") root.mountAction()
        else if (key === "s" && root.setupVisible) root.runSetup("provision")
        else if (key === "u" && root.updateVisible) root.runSetup("update")
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          PanelHero {
            id: hero
            width: parent.width
            title: "Filen"
            meta: root.hasService
              ? (Model.stateLabel(root.state) + (root.unitState !== "" ? " · " + root.unitState : ""))
              : "Unavailable"
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconOpacity: root.running ? 1.0 : 0.65
            iconComponent: Component {
              Text {
                text: Model.stateGlyph(root.state)
                color: root.stateColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
              }
            }
            trailingControl: Component {
              PanelActionButton {
                iconText: "󰑓"
                tooltipText: "Refresh status"
                foreground: root.foreground
                fontFamily: root.fontFamily
                enabled: root.hasService && !root.busy
                onClicked: root.refresh()
              }
            }
          }

          // Transient action feedback, then any error. Errors are elided and
          // carry the full text in a tooltip.
          Item {
            id: messageBlock
            visible: root.hasService && (root.filen.actionStatus !== "" || root.filen.lastError !== "")
            width: parent.width
            implicitHeight: messageText.implicitHeight

            Text {
              id: messageText
              textFormat: Text.PlainText
              width: parent.width
              text: root.hasService
                ? (root.filen.actionStatus !== "" ? root.filen.actionStatus : root.filen.lastError)
                : ""
              color: root.hasService && root.filen.lastError !== "" && root.filen.actionStatus === ""
                ? root.urgent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
              maximumLineCount: 2
              elide: Text.ElideRight
            }

            MouseArea {
              id: messageTooltipArea
              anchors.fill: parent
              hoverEnabled: true
              acceptedButtons: Qt.NoButton
            }

            PanelToolTip {
              visible: messageText.truncated && messageTooltipArea.containsMouse
              text: messageText.text
              fontFamily: root.fontFamily
            }
          }

          // ---- header facts ----
          Column {
            width: parent.width
            spacing: Style.spacing.labelGap

            InfoPair {
              label: "Status"
              value: root.hasService ? String(root.filen.statusText || Model.stateLabel(root.state)) : "Service unavailable"
              valueColor: root.stateColor
            }
            InfoPair {
              label: "Mount"
              value: root.hasService && String(root.filen.mountPath || "") !== ""
                ? String(root.filen.mountPath) : "—"
            }
            InfoPair {
              label: "Unit"
              value: root.unitState !== "" ? root.unitState : "—"
            }
          }

          // ---- primary control ----
          ActionRow {
            id: mountRow
            visible: root.mountVisible
            width: parent.width
            glyph: Model.stateGlyph(root.state)
            glyphColor: root.stateColor
            title: root.busy && root.running ? "Unmounting…" : (root.busy ? "Working…" : root.mountLabel)
            subtitle: root.mountSubtitle
            enabled: root.hasService && !root.busy
            hasCursor: root.cursorActive && root.focusSection === "mount"
            onTriggered: root.mountAction()
            onHoveredIn: root.setSection("mount")
          }

          PanelSeparator { visible: root.actions.files; foreground: root.foreground }

          // ---- storage ----
          Column {
            visible: root.actions.files
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader {
              text: "STORAGE"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            InfoPair {
              label: "Used"
              value: root.usageValue
              valueColor: root.storageStale ? root.dim : root.foreground
            }

            UsageBar {
              width: parent.width
              fraction: root.usageFraction
              fillColor: root.storageStale ? root.dim : root.foreground
            }

            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: {
                if (!root.hasService) return ""
                if (root.storageStale) return "Storage details are out of date."
                return "Updated " + Model.formatRelativeTime(root.filen.checkedAt, root.nowMs).toLowerCase()
              }
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }

          PanelSeparator { visible: root.actions.files; foreground: root.foreground }

          // ---- recent files ----
          Column {
            visible: root.actions.files
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader {
              text: "RECENT FILES"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              visible: root.actions.files && root.remoteFiles.length === 0
              width: parent.width
              text: root.storageStale ? "No recent files available." : "No recent files found."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            Column {
              id: fileColumn
              visible: root.filesVisible
              width: parent.width
              spacing: Style.space(6)

              Repeater {
                model: root.filesVisible ? root.remoteFiles : []
                FileRow {
                  required property var modelData
                  required property int index
                  width: fileColumn.width
                  file: modelData
                  rowIndex: index
                }
              }
            }
          }

          PanelSeparator {
            visible: root.autoLoginVisible || root.setupVisible || root.installVisible
              || root.repairVisible || root.updateVisible
            foreground: root.foreground
          }

          // ---- controls ----
          Toggle {
            id: autoLoginRow
            visible: root.autoLoginVisible
            width: parent.width
            label: "Mount at login"
            description: "Start the Filen mount when you sign in."
            checked: root.autoMountOn
            foreground: root.foreground
            fontFamily: root.fontFamily
            hasCursor: root.cursorActive && root.focusSection === "autologin"
            onClicked: root.toggleAutoMount()
            onHovered: function(isHovered) { if (isHovered) root.setSection("autologin") }
          }

          // ---- actions ----
          ActionRow {
            id: setupRow
            visible: root.setupVisible
            width: parent.width
            glyph: "󰌋"
            title: root.setupLabel
            subtitle: root.setupSubtitle
            hasCursor: root.cursorActive && root.focusSection === "setup"
            onTriggered: root.runSetup("provision")
            onHoveredIn: root.setSection("setup")
          }

          ActionRow {
            id: installRow
            visible: root.installVisible
            width: parent.width
            glyph: "󰇚"
            title: "Install Filen"
            subtitle: "Download the filen binary and write the systemd units"
            hasCursor: root.cursorActive && root.focusSection === "install"
            onTriggered: root.runSetup("install")
            onHoveredIn: root.setSection("install")
          }

          ActionRow {
            id: repairRow
            visible: root.repairVisible
            width: parent.width
            glyph: Model.GLYPH_ALERT
            glyphColor: root.urgent
            title: "Repair Filen"
            subtitle: "Re-write the systemd units and prerequisites"
            hasCursor: root.cursorActive && root.focusSection === "repair"
            onTriggered: root.runSetup("install")
            onHoveredIn: root.setSection("repair")
          }

          // The unit failed: point at its journal so the user can see why
          // before/after repairing (H10).
          Text {
            visible: root.journalHintVisible
            width: parent.width
            textFormat: Text.PlainText
            text: "Unit log: journalctl --user -u omarchy-filen-mount.service"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          // Explicit runtime/unit refresh (H17). Never silent: it opens a
          // terminal running `setup update`, and the settle re-poll reports the
          // new version afterwards.
          ActionRow {
            id: updateRow
            visible: root.updateVisible
            width: parent.width
            glyph: "󰚰"
            title: "Check for updates"
            subtitle: "Refresh the pinned filen runtime and regenerate units"
            hasCursor: root.cursorActive && root.focusSection === "updates"
            onTriggered: root.runSetup("update")
            onHoveredIn: root.setSection("updates")
          }

          // ---- settings (read-only surface of barWidget.schema) ----
          Column {
            visible: root.hasService
            width: parent.width
            spacing: Style.spacing.labelGap

            PanelSeparator { foreground: root.foreground }

            PanelSectionHeader {
              text: "SETTINGS"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            InfoPair {
              label: "Mount folder"
              value: root.hasService
                ? String(root.filen.mountRoot || root.setting("mountRoot", "~/Filen"))
                : String(root.setting("mountRoot", "~/Filen"))
            }
            InfoPair {
              label: "Status refresh"
              value: String(root.hasService ? root.filen.refreshIntervalSec : root.setting("refreshIntervalSec", 15)) + "s"
            }
            InfoPair {
              label: "Storage refresh"
              value: String(root.hasService ? root.filen.apiRefreshMin : root.setting("apiRefreshMin", 10)) + " min"
            }
            InfoPair {
              label: "Cache limit"
              value: String(root.setting("cacheMaxSizeGB", 4)) + " GB"
            }
            InfoPair {
              label: "Show label"
              value: root.setting("showLabel", false) === true ? "Yes" : "No"
            }
          }
        }
      }
    }
  }

  Timer {
    // Keeps "Updated …" and the staleness decision live while the panel is up.
    id: clock
    interval: 30000
    repeat: true
    running: root.opened
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }

  // ---------------------------------------------------------------- rows

  component ActionRow: CursorSurface {
    id: actionRow
    property string glyph: ""
    property string title: ""
    property string subtitle: ""
    property color glyphColor: root.foreground
    signal triggered()
    signal hoveredIn()

    foreground: root.foreground
    opacity: enabled ? 1.0 : 0.5
    implicitHeight: actionContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: actionRow.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onEntered: actionRow.hoveredIn()
      onClicked: actionRow.triggered()
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: actionRow.glyph
        color: actionRow.glyphColor
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        id: actionContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: actionRow.title
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          visible: actionRow.subtitle !== ""
          text: actionRow.subtitle
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }

  component FileRow: CursorSurface {
    id: fileRow
    property var file: null
    property int rowIndex: 0
    readonly property string fileName: file ? String(file.name || "Untitled") : "Untitled"

    hasCursor: root.cursorActive && root.focusSection === "files" && root.fileIndex === rowIndex
    foreground: root.foreground
    implicitHeight: fileContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setFileCursor(fileRow.rowIndex)
      onClicked: root.openFile(fileRow.file)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: "󰈔"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        id: fileContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: fileRow.fileName
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: root.fileMeta(fileRow.file)
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }

  component UsageBar: Item {
    id: usageBar
    property real fraction: 0
    property color fillColor: root.foreground

    width: parent ? parent.width : implicitWidth
    implicitHeight: Style.space(6)
    height: implicitHeight

    Rectangle {
      id: usageTrack
      anchors.fill: parent
      radius: height / 2
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
    }

    Rectangle {
      anchors.left: usageTrack.left
      anchors.verticalCenter: usageTrack.verticalCenter
      height: usageTrack.height
      radius: usageTrack.radius
      color: usageBar.fillColor
      width: Math.max(usageTrack.height, usageTrack.width * Math.max(0, Math.min(1, usageBar.fraction)))

      Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
      Behavior on color { ColorAnimation { duration: 160 } }
    }
  }

  component InfoPair: Row {
    id: infoPair
    property string label: ""
    property string value: ""
    property color valueColor: root.foreground

    width: parent ? parent.width : implicitWidth
    spacing: Style.space(8)

    InfoLabel { text: infoPair.label }
    Item {
      width: Math.max(0, parent.width - parent.children[0].implicitWidth - parent.children[2].implicitWidth - parent.spacing * 2)
      height: 1
    }
    InfoValue {
      text: infoPair.value
      color: infoPair.valueColor
    }
  }

  component InfoLabel: Text {
    textFormat: Text.PlainText
    color: root.foreground
    opacity: 0.6
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  component InfoValue: Text {
    textFormat: Text.PlainText
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    elide: Text.ElideRight
  }

  function fileMeta(file) {
    if (!file) return ""
    var parts = []
    if (file.folder) parts.push(String(file.folder))
    parts.push(Model.formatRelativeTime(file.modifiedTs, root.nowMs))
    parts.push(Model.formatBytes(file.sizeBytes))
    return parts.join(" · ")
  }
}
