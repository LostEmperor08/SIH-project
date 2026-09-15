/**
 * Storage that cannot throw.
 *
 * iOS Safari in Private Browsing raises a SecurityError on the first touch of
 * localStorage — not on write, on *access*. An unguarded read during render
 * takes the whole app down, which is how the site came up unstyled on iPhone.
 * Everything goes through here instead.
 */
let store = null;
let probed = false;

function backing() {
  if (probed) return store;
  probed = true;
  try {
    const key = "__cv_probe__";
    window.localStorage.setItem(key, "1");
    window.localStorage.removeItem(key);
    store = window.localStorage;
  } catch {
    store = null; // private mode, disabled storage, or a sandboxed frame
  }
  return store;
}

/** In-memory stand-in so preferences still hold for the session. */
const memory = new Map();

export function readPref(key, fallback = null) {
  const s = backing();
  if (!s) return memory.has(key) ? memory.get(key) : fallback;
  try {
    const value = s.getItem(key);
    return value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

export function writePref(key, value) {
  memory.set(key, String(value));
  const s = backing();
  if (!s) return;
  try {
    s.setItem(key, String(value));
  } catch {
    /* quota or private mode — the memory copy stands in */
  }
}

export function readSession(key, fallback = null) {
  try {
    const value = window.sessionStorage.getItem(key);
    return value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

export function writeSession(key, value) {
  try {
    window.sessionStorage.setItem(key, String(value));
  } catch {
    /* ignore */
  }
}
