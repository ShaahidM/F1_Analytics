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
