#!/usr/bin/env node
"use strict"

var fs = require("fs")
var path = require("path")
var vm = require("vm")

var source = fs
  .readFileSync(path.join(__dirname, "..", "Model.js"), "utf8")
  .replace(/^[ \t]*\.pragma[ \t]+library[ \t]*\r?\n/m, "")

var sandbox = { module: { exports: {} }, exports: {}, console: console }
vm.createContext(sandbox)
vm.runInContext(source, sandbox, { filename: "Model.js" })
var Model = sandbox.module.exports

var checks = 0
var failures = 0

function assertEqual(actual, expected, label) {
  checks += 1
  if (actual !== expected) {
    failures += 1
    console.error(
      "FAIL " + label + ": expected " + JSON.stringify(expected) +
      ", got " + JSON.stringify(actual)
    )
  }
}

assertEqual(typeof Model.parseStatus, "function", "parseStatus exported")
assertEqual(typeof Model.defaultStatus, "function", "defaultStatus exported")

assertEqual(Model.defaultStatus().ok, true, "defaultStatus().ok")
assertEqual(Array.isArray(Model.defaultStatus().files), true, "defaultStatus().files")

var badJson = Model.parseStatus("{ not json")
assertEqual(badJson.ok, false, "parseStatus(garbage).ok")
assertEqual(Array.isArray(badJson.files), true, "parseStatus(garbage).files")

var blank = Model.parseStatus("")
assertEqual(blank.ok, false, "parseStatus(blank).ok")

var nonObject = Model.parseStatus("[1,2,3]")
assertEqual(nonObject.ok, false, "parseStatus(array).ok")

var good = Model.parseStatus(JSON.stringify({ ok: true, running: true, files: null }))
assertEqual(good.ok, true, "parseStatus(valid).ok")
assertEqual(good.running, true, "parseStatus(valid).running")
assertEqual(Array.isArray(good.files), true, "parseStatus(valid).files coerced")
assertEqual(good.quotaKnown, false, "parseStatus(valid) defaults preserved")

var mounted = { ok: true, installed: true, authenticated: true, running: true }
assertEqual(Model.stateFor(mounted), "mounted", "stateFor mounted")
assertEqual(
  Model.stateFor({ ok: true, installed: true, authenticated: false }),
  "needs-auth", "stateFor unauthenticated"
)
assertEqual(
  Model.stateFor({ ok: true, installed: false }),
  "not-installed", "stateFor not installed"
)
assertEqual(Model.stateLabel("not-installed"), "Not installed", "stateLabel not installed")
assertEqual(Model.stateGlyph("not-installed"), Model.GLYPH_STOPPED, "stateGlyph not installed")

assertEqual(typeof Model.stateTone, "function", "stateTone exported")
assertEqual(Model.stateTone("failed"), "urgent", "stateTone failed")
assertEqual(Model.stateTone("needs-auth"), "accent", "stateTone needs-auth")
assertEqual(Model.stateTone("not-installed"), "accent", "stateTone not-installed")
assertEqual(Model.stateTone("mounted"), "normal", "stateTone mounted")
assertEqual(Model.stateTone("mounting"), "normal", "stateTone mounting")
assertEqual(Model.stateTone("stopped"), "normal", "stateTone stopped")
assertEqual(Model.stateTone(""), "normal", "stateTone unknown defaults normal")
assertEqual(Model.stateFor({ ok: false }), "failed", "stateFor failure doc")
assertEqual(
  Model.stateFor({ ok: true, installed: true, authenticated: true, running: false }),
  "stopped", "stateFor stopped"
)
assertEqual(
  Model.stateFor({ ok: true, installed: true, authenticated: true, unitState: "failed" }),
  "failed", "stateFor failed unit"
)
assertEqual(
  Model.stateFor({ ok: true, installed: true, authenticated: true, unitState: "activating" }),
  "mounting", "stateFor mounting unit"
)

assertEqual(Model.formatBytes(0), "0 B", "formatBytes(0)")
assertEqual(Model.formatBytes(-5), "0 B", "formatBytes(negative)")
assertEqual(Model.formatBytes(512), "512 B", "formatBytes(512)")
assertEqual(Model.formatBytes(1024), "1 KB", "formatBytes(1KiB)")
assertEqual(Model.formatBytes(1048576), "1 MB", "formatBytes(1MiB)")
assertEqual(Model.formatBytes(1610612736), "1.5 GB", "formatBytes(1.5GiB)")

assertEqual(
  Model.usageText({ quotaKnown: true, usedBytes: 1024, quotaBytes: 2048 }),
  "1 KB of 2 KB", "usageText known quota"
)
assertEqual(
  Model.usageText({ quotaKnown: false, usedBytes: 1024, quotaBytes: 2048 }),
  "1 KB", "usageText unknown quota"
)
assertEqual(
  Model.usageFraction({ quotaKnown: true, usedBytes: 512, quotaBytes: 1024 }),
  0.5, "usageFraction known quota"
)
assertEqual(
  Model.usageFraction({ quotaKnown: false, usedBytes: 512, quotaBytes: 1024 }),
  0, "usageFraction unknown quota"
)

assertEqual(
  Model.fileUri("/home/u/Filen/My File.txt"),
  "file:///home/u/Filen/My%20File.txt", "fileUri with spaces"
)
assertEqual(
  Model.fileUri("/home/u/Filen"),
  "file:///home/u/Filen", "fileUri plain"
)
assertEqual(Model.fileUri(""), "file://", "fileUri empty")

assertEqual(typeof Model.filesVisible, "function", "filesVisible exported")
assertEqual(Model.filesVisible(true, 3, true), true, "filesVisible running+enabled+files")
assertEqual(Model.filesVisible(true, 3, false), false, "filesVisible disabled hides")
assertEqual(Model.filesVisible(true, 0, true), false, "filesVisible empty hides")
assertEqual(Model.filesVisible(false, 3, true), false, "filesVisible not-running hides")
assertEqual(Model.filesVisible(true, 3, undefined), true, "filesVisible defaults enabled")
assertEqual(Model.filesVisible(true, "2", true), true, "filesVisible coerces count")

if (failures > 0) {
  console.error("FAILED: " + failures + " of " + checks + " assertions")
  process.exit(1)
}
console.log("ok: " + checks + " assertions passed")
