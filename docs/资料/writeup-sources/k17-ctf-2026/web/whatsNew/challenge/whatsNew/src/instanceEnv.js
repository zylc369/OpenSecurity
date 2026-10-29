"use strict";

// Reads per-instance secrets the instantiator injects into /run/instantiator.env AFTER the
// VM is restored from the template snapshot. The app boots from the snapshot before this
// file exists, so these values must be read at REQUEST time, never cached at module load.
// Falls back to process.env for local (docker-compose) runs.

const fs = require("fs");

const ENV_FILE = process.env.INSTANCE_ENV_PATH || "/run/instantiator.env";

let cache = null;

function load() {
  if (cache) return cache;
  let text;
  try {
    text = fs.readFileSync(ENV_FILE, "utf8");
  } catch {
    return {}; // not injected yet (build / readiness-probe time); don't cache the miss
  }
  const parsed = {};
  for (const line of text.split("\n")) {
    const eq = line.indexOf("=");
    if (eq > 0) parsed[line.slice(0, eq)] = line.slice(eq + 1);
  }
  cache = parsed; // values are fixed for the life of the instance
  return cache;
}

function instanceEnv(key, fallback) {
  const value = load()[key];
  if (value !== undefined && value !== "") return value;
  const fromProcess = process.env[key];
  if (fromProcess !== undefined && fromProcess !== "") return fromProcess;
  return fallback;
}

module.exports = { instanceEnv };
