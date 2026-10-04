.pragma library

var GLYPH_MOUNTED = "󰅠"
var GLYPH_MOUNTING = "󰘿"
var GLYPH_STOPPED = "󰅤"
var GLYPH_ALERT = "󰧠"

function defaultStatus() {
  return {
    ok: true,
    installed: false,
    authenticated: false,
    running: false,
    statusText: "Unavailable",
    mountPath: "",
    unitState: "",
    autoMount: false,
    // Kept for parity with the dropbox contract; no plan data is ever emitted.
    plan: null,
    usedBytes: 0,
    quotaBytes: 0,
    usagePercent: 0,
    quotaKnown: false,
    files: [],
    checkedAt: 0
  }
}

function unavailableStatus(message) {
  var status = defaultStatus()
  status.ok = false
  status.error = message
  return status
}

function parseStatus(raw) {
  var text = String(raw === null || raw === undefined ? "" : raw).trim()
  if (text === "") return unavailableStatus("No status available")

  var parsed
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return unavailableStatus("Could not read Filen status")
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return unavailableStatus("Bad status output")
  }

  var status = defaultStatus()
  for (var key in parsed) {
    if (Object.prototype.hasOwnProperty.call(parsed, key)) status[key] = parsed[key]
  }
  if (!Array.isArray(status.files)) status.files = []
  return status
}

function formatBytes(bytes) {
  var n = Number(bytes || 0)
  if (!isFinite(n) || n <= 0) return "0 B"
  var units = ["B", "KB", "MB", "GB", "TB", "PB"]
  var index = 0
  while (n >= 1024 && index < units.length - 1) {
    n /= 1024
    index += 1
  }
  var decimals = index <= 1 ? 0 : (n < 10 ? 1 : 0)
  var text = n.toFixed(decimals)
  if (text.indexOf(".") >= 0) {
    text = text.replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1")
  }
  return text + " " + units[index]
}

function usageText(remote) {
  if (!remote) return ""
  var quota = Number(remote.quotaBytes || 0)
  if (remote.quotaKnown && quota > 0) {
    return formatBytes(remote.usedBytes) + " of " + formatBytes(quota)
  }
  return formatBytes(remote.usedBytes)
}

function usageFraction(remote) {
  if (!remote || !remote.quotaKnown) return 0
  var quota = Number(remote.quotaBytes || 0)
  if (!isFinite(quota) || quota <= 0) return 0
  var fraction = Number(remote.usedBytes || 0) / quota
  if (!isFinite(fraction)) return 0
  return Math.max(0, Math.min(1, fraction))
}

function stateLabel(state) {
  switch (state) {
    case "mounted": return "Mounted"
    case "mounting": return "Mounting"
    case "failed": return "Failed"
    case "needs-auth": return "Sign-in needed"
    case "stopped": return "Stopped"
    case "not-installed": return "Not installed"
    default: return "Off"
  }
}

function stateGlyph(state) {
  switch (state) {
    case "mounted": return GLYPH_MOUNTED
    case "mounting": return GLYPH_MOUNTING
    case "failed": return GLYPH_ALERT
    case "needs-auth": return GLYPH_ALERT
    case "not-installed": return GLYPH_STOPPED
    default: return GLYPH_STOPPED
  }
}

// One tone per state, so the bar and panel colour the icon from a single source
// rather than repeating the same state switch in QML.
function stateTone(state) {
  switch (state) {
    case "failed": return "urgent"
    case "needs-auth": return "accent"
    case "not-installed": return "accent"
    default: return "normal"
  }
}

// Single-account status document (see .scratch/omarchy-filen/status-contract.md)
// mapped to one worst-first state string. Not-installed is its own state, not a
// signed-out one: the panel offers Install (not Set up) and the bar shows no
// auth alert. The panel branches its action on the raw installed/authenticated
// flags; the bar shows the state.
function stateFor(status) {
  if (!status || status.ok === false) return "failed"
  if (status.installed === false) return "not-installed"
  if (status.authenticated === false) return "needs-auth"
  var unit = String(status.unitState || "")
  if (unit === "activating" || unit === "reloading") return "mounting"
  if (unit === "failed") return "failed"
  if (status.running === true) return "mounted"
  return "stopped"
}

// The one action each condition wants, derived from the status contract rather
// than ad-hoc flag combinations in the panel. Returns a plain object of booleans
// so each row's `visible` binds to one source of truth, and so the rule set is
// unit-testable without QML. A signed-out state never offers Mount; a failed
// unit never offers Mount either (it needs Repair first).
function noActions() {
  return {
    install: false,
    setup: false,
    mount: false,
    autoLogin: false,
    repair: false,
    updates: false,
    files: false,
    journalHint: false
  }
}

function panelActions(status) {
  if (status === null || status === undefined) return noActions()

  // The status helper itself failed: `setup install` is idempotent, so offer
  // Repair and the unit log. Installed-ness is unknown, so nothing else shows.
  if (status.ok === false) {
    var broken = noActions()
    broken.repair = true
    broken.journalHint = true
    return broken
  }

  var installed = status.installed === true
  if (!installed) {
    var missing = noActions()
    missing.install = true
    return missing
  }

  var authenticated = status.authenticated === true
  if (!authenticated) {
    var auth = noActions()
    auth.setup = true
    auth.updates = true
    return auth
  }

  // Installed and signed in, but the unit failed: repair, never mount; point at
  // the unit's journal (H10).
  if (String(status.unitState || "") === "failed") {
    var failed = noActions()
    failed.repair = true
    failed.updates = true
    failed.journalHint = true
    return failed
  }

  // Installed, signed in, unit healthy: mount when stopped, unmount when running.
  var live = noActions()
  live.mount = true
  live.autoLogin = true
  live.updates = true
  live.files = status.running === true
  return live
}

function fileUri(path) {
  var parts = String(path === null || path === undefined ? "" : path).split("/")
  for (var i = 0; i < parts.length; i++) parts[i] = encodeURIComponent(parts[i])
  return "file://" + parts.join("/")
}

function formatRelativeTime(timestampSec, nowMs) {
  var ts = Number(timestampSec || 0)
  if (!isFinite(ts) || ts <= 0) return "Unknown time"
  var now = nowMs === undefined ? Date.now() : Number(nowMs)
  var diff = Math.max(0, Math.floor((now - ts * 1000) / 1000))
  if (diff < 60) return "Just now"
  var minutes = Math.floor(diff / 60)
  if (minutes < 60) return minutes + "m ago"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return hours + "h ago"
  var days = Math.floor(hours / 24)
  if (days < 30) return days + "d ago"
  var months = Math.floor(days / 30)
  if (months < 12) return months + "mo ago"
  return Math.floor(days / 365) + "y ago"
}

if (typeof module !== "undefined") {
  module.exports = {
    GLYPH_MOUNTED: GLYPH_MOUNTED,
    GLYPH_MOUNTING: GLYPH_MOUNTING,
    GLYPH_STOPPED: GLYPH_STOPPED,
    GLYPH_ALERT: GLYPH_ALERT,
    defaultStatus: defaultStatus,
    parseStatus: parseStatus,
    formatBytes: formatBytes,
    usageText: usageText,
    usageFraction: usageFraction,
    stateLabel: stateLabel,
    stateGlyph: stateGlyph,
    stateTone: stateTone,
    stateFor: stateFor,
    noActions: noActions,
    panelActions: panelActions,
    fileUri: fileUri,
    formatRelativeTime: formatRelativeTime
  }
}
