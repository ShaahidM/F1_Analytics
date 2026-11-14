import type { Trace } from "./api";

/** Index on the trace's distance grid nearest to `s`. */
export function gridIndex(tr: Trace, s: number): number {
  return Math.max(0, Math.min(tr.s.length - 1, Math.round(s / tr.grid_m)));
}

/** Lap-relative elapsed time on the grid, zeroed at s = 0. */
export function elapsed(tr: Trace): (number | null)[] {
  const t0 = tr.t.find((v) => v !== null) ?? 0;
  return tr.t.map((v) => (v === null ? null : v - t0));
}

/** Track distance reached `tau` seconds into the lap (inverse of elapsed time; linear between grid points). */
export function sAtTime(tr: Trace, tau: number): number {
  const e = elapsed(tr);
  let lo = 0;
  let hi = e.length - 1;
  if (tau <= (e[0] ?? 0)) return tr.s[0];
  if (tau >= (e[hi] ?? Infinity)) return tr.s[hi];
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((e[mid] ?? 0) <= tau) lo = mid;
    else hi = mid;
  }
  const e0 = e[lo] ?? 0;
  const e1 = e[hi] ?? e0;
  const f = e1 > e0 ? (tau - e0) / (e1 - e0) : 0;
  return tr.s[lo] + f * (tr.s[hi] - tr.s[lo]);
}

/** Lap duration according to the trace's own elapsed-time channel. */
export function traceDuration(tr: Trace): number {
  const e = elapsed(tr);
  return e[e.length - 1] ?? 0;
}

/** Δt(s) = t_B(s) − t_A(s). Positive means B is behind A at that distance. */
export function deltaTime(a: Trace, b: Trace): (number | null)[] {
  const ea = elapsed(a);
  const eb = elapsed(b);
  const n = Math.min(ea.length, eb.length);
  const out: (number | null)[] = [];
  for (let i = 0; i < n; i++) {
    const va = ea[i];
    const vb = eb[i];
    out.push(va === null || vb === null ? null : vb - va);
  }
  return out;
}

export function fmtLap(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "—";
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return m > 0 ? `${m}:${s.toFixed(3).padStart(6, "0")}` : s.toFixed(3);
}
