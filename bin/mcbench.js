#!/usr/bin/env node
// Thin launcher: `npx github:<you>/mcbench demo` -> python3 -m mcbench demo
const { spawnSync } = require("child_process");
const path = require("path");
const args = process.argv.slice(2);
const py = process.platform === "win32" ? "python" : "python3";
const r = spawnSync(py, ["-m", "mcbench", ...(args.length ? args : ["demo"])], {
  stdio: "inherit", cwd: path.join(__dirname, ".."),
});
process.exit(r.status ?? 1);
