import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// Headless singleton behind the Filen plugin.
//
// A bar widget is instantiated once per monitor, so all polling and control
// lives here: the shell mounts exactly one service per plugin, and a
// two-monitor setup must not double the work.
//
// The service deliberately owns no mount and no credential. `filen mount` runs
// under systemd (omarchy-filen-mount.service), because a mount parented to the shell
// process would be torn down by `omarchy restart shell` and by every plugin
// hot-reload, taking open files with it. Everything here is therefore a read
// of local, non-secret state, or a short-lived `systemctl --user` command.
Item {
  id: root

  // Injected by the shell.
  property var shell: null
  property var settings: ({})

  // ---------------------------------------------------------------- state

  property bool ok: true
  property bool installed: false
  property bool authenticated: false
  property bool running: false
  property string statusText: ""
  property string mountPath: ""
  property string unitState: ""
  property bool autoMount: false
  property var plan: null
  property double usedBytes: 0
  property double quotaBytes: 0
  property double usagePercent: 0
  property bool quotaKnown: false
  property var files: []
  property double checkedAt: 0
  property bool refreshing: false
  property string lastError: ""
  property string actionStatus: ""

  // Optimistic state while a systemctl action settles; "" means "trust the
  // poll". Mirrors the cloud/dropbox services' pending-state handling.
  property string _pendingState: ""

  // The mount settings last written to settings.conf; a re-push of the same
  // pair is a no-op. `-1` makes the first push (Component.onCompleted) land.
  property string _pushedMountRoot: ""
  property int _pushedCacheMaxSizeGB: -1
  // The first push only mirrors settings to disk; a live mount is restarted
  // solely for a change made after that, so a shell start / hot-reload never
  // drops the user's mount.
  property bool _settingsInitialized: false

  readonly property string state: _pendingState !== ""
    ? _pendingState
    : Model.stateFor({ ok: ok, installed: installed, authenticated: authenticated, unitState: unitState, running: running })
  readonly property bool busy: statusProcess.running || controlProcess.running

  // ---------------------------------------------------------------- settings

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function intSetting(name, fallback, min, max) {
    var n = parseInt(String(setting(name, fallback)), 10)
    if (!isFinite(n)) n = fallback
    return Math.max(min, Math.min(max, n))
  }

  readonly property string mountRoot: String(setting("mountRoot", "~/Filen"))
  readonly property int cacheMaxSizeGB: intSetting("cacheMaxSizeGB", 4, 1, 512)
  readonly property int refreshIntervalSec: intSetting("refreshIntervalSec", 15, 5, 300)
  readonly property int apiRefreshMin: intSetting("apiRefreshMin", 10, 5, 240)
  readonly property bool showLabel: setting("showLabel", false) === true

  // The API fragment ages out at twice the refresh cadence, matching the status
  // helper's API_MAX_AGE_SECONDS. Keeping the rule here lets the panel read one
  // value instead of re-deriving it.
  readonly property int staleAfterSec: apiRefreshMin * 120

  // ---------------------------------------------------------------- paths
  //
  // The shell injects `settings` but not the plugin's own directory, and
  // first-party plugins cheat by reading OMARCHY_PATH -- which resolves to the
  // packaged tree, not here. Qt.resolvedUrl is relative to this file, so it
  // works wherever the plugin is installed.
  function scriptPath(name) {
    return Qt.resolvedUrl("bin/" + name).toString().replace(/^file:\/\//, "")
  }

  readonly property string statusScript: scriptPath("status")
  readonly property string setupScript: scriptPath("setup")

  // ---------------------------------------------------------------- reading

  function refresh() {
    if (statusProcess.running) return
    refreshing = true
    statusProcess.command = ["python3", statusScript, "--mount-root", mountRoot]
    statusProcess.running = true
  }

  function applyStatus(raw) {
    var parsed = Model.parseStatus(raw)
    ok = parsed.ok !== false
    installed = parsed.installed === true
    authenticated = parsed.authenticated === true
    running = parsed.running === true
    statusText = String(parsed.statusText || "")
    mountPath = String(parsed.mountPath || "")
    unitState = String(parsed.unitState || "")
    autoMount = parsed.autoMount === true
    plan = parsed.plan === undefined ? null : parsed.plan
    usedBytes = Number(parsed.usedBytes || 0)
    quotaBytes = Number(parsed.quotaBytes || 0)
    usagePercent = Number(parsed.usagePercent || 0)
    quotaKnown = parsed.quotaKnown === true
    files = parsed.files || []
    checkedAt = Number(parsed.checkedAt || 0)
    lastError = parsed.ok === false ? String(parsed.error || "Could not read Filen status") : ""
    if (_pendingState === "mounting" && running) _pendingState = ""
    else if (_pendingState === "stopped" && !running) _pendingState = ""
  }

  // ---------------------------------------------------------------- control
  //
  // Reflect the action immediately rather than waiting for the next poll:
  // systemd takes a beat to settle, and a button that appears to do nothing for
  // two seconds reads as broken. The settle poll corrects any optimism.
  function runControl(args, failureMessage) {
    if (controlProcess.running) return false
    controlProcess.failureMessage = failureMessage || "Command failed"
    controlProcess.command = ["systemctl", "--user"].concat(args)
    controlProcess.running = true
    return true
  }

  function mount() {
    if (controlProcess.running) return
    _pendingState = "mounting"
    actionStatus = "Mounting…"
    actionStatusTimer.restart()
    runControl(["start", "omarchy-filen-mount.service"], "Could not mount Filen")
  }

  function unmount() {
    if (controlProcess.running) return
    _pendingState = "stopped"
    actionStatus = "Unmounting…"
    actionStatusTimer.restart()
    runControl(["stop", "omarchy-filen-mount.service"], "Could not unmount Filen")
  }

  function restart() {
    if (controlProcess.running) return
    _pendingState = "mounting"
    actionStatus = "Restarting…"
    actionStatusTimer.restart()
    runControl(["restart", "omarchy-filen-mount.service"], "Could not restart Filen")
  }

  function toggleMount() {
    if (running || state === "mounting") unmount()
    else if (state !== "needs-auth" && state !== "failed") mount()
  }

  // Autostart only: this enables/disables the unit for future logins and must
  // not start or stop the mount the user is using right now. Session control
  // stays in mount()/unmount().
  function setAutoMount(on) {
    if (controlProcess.running) return
    runControl([on ? "enable" : "disable", "omarchy-filen-mount.service"], "Could not change the login setting")
  }

  // ---------------------------------------------------------------- settings push
  //
  // The mount unit reads settings.conf once, at start, so an edit only takes
  // effect on the next start. Debounce edits (and the startup push) into one
  // write, then restart a live mount so the new flags apply now.
  function pushMountSettings() {
    mountSettingsTimer.restart()
  }

  function flushMountSettings() {
    if (mountRoot === _pushedMountRoot && cacheMaxSizeGB === _pushedCacheMaxSizeGB) return
    if (settingsProcess.running) {
      // A push is already in flight; re-check once it lands.
      mountSettingsTimer.restart()
      return
    }
    // Snapshot what this run carries so a settings change landing mid-flight
    // is not recorded as applied.
    settingsProcess.appliedMountRoot = mountRoot
    settingsProcess.appliedCacheMaxSizeGB = cacheMaxSizeGB
    settingsProcess.command = ["bash", setupScript, "settings",
      "MOUNT_ROOT=" + mountRoot, "CACHE_SIZE=" + cacheMaxSizeGB + "G"]
    settingsProcess.running = true
  }

  // ---------------------------------------------------------------- timers

  Timer {
    // Cheap: local probes only, no network, no credential.
    id: pollTimer
    interval: root.refreshIntervalSec * 1000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    // After boot the mount unit may still be activating when the first poll
    // lands, leaving the bar stale until the next cycle. Poll quickly until it
    // shows up, or give up after ~30 seconds.
    id: startupRamp
    property int ticks: 0
    interval: 2000
    repeat: true
    running: true
    onTriggered: {
      ticks += 1
      if (root.running || ticks >= 15) startupRamp.running = false
      else root.refresh()
    }
  }

  Timer {
    // After a control command, re-poll a handful of times so the panel catches
    // up without waiting a full cycle; clear the optimistic override at the end.
    id: settleTimer
    property int ticks: 0
    interval: 1500
    repeat: true
    running: false
    onTriggered: {
      ticks += 1
      root.refresh()
      if (ticks >= 4) {
        ticks = 0
        settleTimer.running = false
        root._pendingState = ""
      }
    }
    onRunningChanged: if (running) ticks = 0
  }

  Timer {
    id: actionStatusTimer
    interval: 2200
    repeat: false
    onTriggered: root.actionStatus = ""
  }

  Timer {
    // Restart-on-change debounce: each settings edit resets the 800ms window,
    // so only the final values are written.
    id: mountSettingsTimer
    interval: 800
    repeat: false
    onTriggered: root.flushMountSettings()
  }

  // ---------------------------------------------------------------- processes

  Process {
    id: statusProcess
    running: false
    command: []
    stdout: StdioCollector { id: statusOut; waitForEnd: true }
    stderr: StdioCollector { id: statusErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.refreshing = false
      if (exitCode === 0) root.applyStatus(statusOut.text)
      else root.lastError = String(statusErr.text || "Could not read Filen status").substring(0, 160)
    }
  }

  Process {
    id: controlProcess
    property string failureMessage: ""
    running: false
    command: []
    stdout: StdioCollector { id: controlOut; waitForEnd: true }
    stderr: StdioCollector { id: controlErr; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        var reason = String(controlErr.text || controlOut.text || "").trim()
        root.lastError = (failureMessage + (reason ? ": " + reason : "")).substring(0, 200)
        root.actionStatus = ""
        root._pendingState = ""
      } else {
        root.lastError = ""
      }
      settleTimer.ticks = 0
      settleTimer.restart()
    }
  }

  Process {
    id: settingsProcess
    // What this run writes; recorded as applied only once it exits cleanly.
    property string appliedMountRoot: ""
    property int appliedCacheMaxSizeGB: 0
    running: false
    command: []
    stdout: StdioCollector { id: settingsOut; waitForEnd: true }
    stderr: StdioCollector { id: settingsErr; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        var reason = String(settingsErr.text || settingsOut.text || "").trim()
        root.lastError = ("Could not apply mount settings" + (reason ? ": " + reason : "")).substring(0, 200)
        return
      }
      var first = !root._settingsInitialized
      root._pushedMountRoot = appliedMountRoot
      root._pushedCacheMaxSizeGB = appliedCacheMaxSizeGB
      root._settingsInitialized = true
      // The unit read the old flags at start, so a live mount needs a restart —
      // but only for a change made after the initial mirror; a shell start must
      // not restart an existing mount. A stopped unit picks flags up on start.
      if (!first && root.running) root.restart()
    }
  }

  // A settings edit re-runs the debounced push; skip if the pair is unchanged.
  onMountRootChanged: pushMountSettings()
  onCacheMaxSizeGBChanged: pushMountSettings()

  // Nothing destructive: the startup poll is timer-driven (`triggeredOnStart`).
  // This service never authenticates, never reads the credential, and never
  // runs `filen`; it only probes local state and drives `systemctl --user`.
  // The initial push only mirrors settings to disk (`_settingsInitialized`
  // gates the restart), so a shell start never drops an existing mount.
  Component.onCompleted: pushMountSettings()
}
