/**
 * Device-aware motion budget.
 *
 * The page is built on two expensive effects: a rotating radar backdrop and
 * backdrop-filter glass on top of it. Together they force the compositor to
 * re-blur every frame, which is fine on a desktop GPU and miserable on a thin
 * laptop or a mid-range phone. So we measure the device once and let CSS
 * decide how much of the effect it can afford.
 *
 * Sets on <html>:
 *   .perf-lite  — heavy blur off, radar held still
 *   .perf-mid   — reduced blur, radar still animates
 * and --fps-cap, the refresh rate we actually observed.
 */

const STORE_KEY = "chakravyuh_perf_tier";

function staticHints() {
  const mem = navigator.deviceMemory ?? 8;
  const cores = navigator.hardwareConcurrency ?? 8;
  const slowNet = navigator.connection?.saveData === true;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  if (slowNet || mem <= 2 || cores <= 2) return "lite";
  if (mem <= 4 || cores <= 4 || (coarse && window.innerWidth < 900)) return "mid";
  return "full";
}

function apply(tier, hz) {
  const root = document.documentElement;
  root.classList.toggle("perf-lite", tier === "lite");
  root.classList.toggle("perf-mid", tier === "mid");
  if (hz) root.style.setProperty("--fps-cap", String(hz));
}

/** Samples real frame pacing for ~600ms and downgrades if we miss frames. */
function measure(initial) {
  let frames = 0;
  let long = 0;
  let last = performance.now();
  const start = last;

  const tick = (now) => {
    const dt = now - last;
    last = now;
    frames += 1;
    // Anything past ~24ms means we already dropped a frame at 60Hz.
    if (dt > 24) long += 1;
    if (now - start < 600) {
      requestAnimationFrame(tick);
      return;
    }

    const elapsed = (now - start) / 1000;
    const fps = frames / elapsed;
    const hz = fps > 90 ? 120 : fps > 45 ? 60 : Math.round(fps);
    const dropRate = long / frames;

    let tier = initial;
    // Judge against the display's own ceiling, not a flat 60.
    if (dropRate > 0.35 && fps < hz * 0.75) tier = tier === "full" ? "mid" : "lite";
    if (fps < 35) tier = "lite";

    apply(tier, hz);
    try {
      sessionStorage.setItem(STORE_KEY, tier);
    } catch {
      /* private mode */
    }
  };

  requestAnimationFrame(tick);
}

export function initPerfTier() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    apply("lite", 60);
    return;
  }

  let cached = null;
  try {
    cached = sessionStorage.getItem(STORE_KEY);
  } catch {
    /* ignore */
  }

  const hinted = cached ?? staticHints();
  apply(hinted, null);

  // Re-measure each load; conditions change (battery saver, other tabs).
  if (document.readyState === "complete") measure(hinted);
  else window.addEventListener("load", () => measure(hinted), { once: true });
}

export default initPerfTier;
