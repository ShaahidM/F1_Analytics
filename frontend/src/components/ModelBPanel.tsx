"use client";

import { useQuery } from "@tanstack/react-query";
import type { Data } from "plotly.js-dist-min";
import { api, type Coef } from "@/lib/api";
import { COMPOUND, DRIVER } from "@/lib/colors";
import { Badge } from "./Badge";
import { Plot } from "./Plot";

type Slot = { slot: "a" | "b"; driver: number; label: string };
const FIELD = "#8a8984";

const fmtCoef = (c: Coef, d = 3) => `${c.estimate >= 0 ? "+" : ""}${c.estimate.toFixed(d)} [${c.ci_low.toFixed(d)}, ${c.ci_high.toFixed(d)}]`;

/** Session-wide fixed-effects model: separates the shared fuel/track trend from per-compound tyre-age effects. */
export function ModelBPanel({ sessionId, slots, includeFlagged }: { sessionId: string; slots: Slot[]; includeFlagged: boolean }) {
  const q = useQuery({
    queryKey: ["modelB", sessionId, slots.map((s) => s.driver), includeFlagged],
    queryFn: () => api.model(sessionId, slots.map((s) => s.driver), includeFlagged),
    retry: false,
  });
  if (q.isLoading) return <div className="p-3 text-xs text-ink-3">Fitting the session-wide model…</div>;
  if (q.isError) return <div className="p-3 text-xs text-ink-3">{(q.error as Error).message}</div>;
  const m = q.data;
  if (!m) return null;
  if (!m.ok) return <div className="p-3 text-xs text-warn">Model B not fitted: {m.reason}</div>;

  const compounds = Object.keys(m.field_tyre_slopes);
  // Dot-and-whisker: one row per compound × (field, A, B).
  const rows: { y: string; c: Coef; color: string }[] = [];
  for (const c of compounds) {
    rows.push({ y: `${c} · field`, c: m.field_tyre_slopes[c], color: FIELD });
    (["A", "B"] as const).forEach((tag, i) => {
      const v = m.driver_tyre_slopes[tag].compounds[c];
      if (v) rows.push({ y: `${c} · ${slots[i].label}`, c: v, color: DRIVER[slots[i].slot] });
    });
  }
  const data: Data[] = rows.map((r) => ({
    type: "scatter", mode: "markers", x: [r.c.estimate], y: [r.y], showlegend: false,
    marker: { color: r.color, size: 9, line: { color: "#1a1a19", width: 2 } },
    error_x: { type: "data", symmetric: false, array: [r.c.ci_high - r.c.estimate], arrayminus: [r.c.estimate - r.c.ci_low], color: r.color, thickness: 1.5, width: 4 },
    hovertemplate: `${r.y}: ${fmtCoef(r.c)} s/lap<extra></extra>`,
  }));

  return (
    <section className="card p-2">
      <h3 className="flex flex-wrap items-center gap-2 px-1 text-xs font-semibold">
        Session-wide model (Model B): tyre-age effect with fuel and track evolution separated
        <Badge tier="E" note={`OLS with driver fixed effects, HC3 robust SE, ${m.ci_level * 100}% CI`} />
      </h3>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Plot height={Math.max(180, rows.length * 34 + 60)} data={data}
          layout={{ xaxis: { title: { text: "Lap-time cost per lap of tyre age (s/lap)" }, zeroline: true },
            yaxis: { autorange: "reversed", automargin: true }, margin: { l: 110, r: 12, t: 10, b: 44 } }} />
        <div className="flex flex-col gap-2 text-xs text-ink-2">
          <table className="w-full">
            <tbody className="font-mono">
              <tr><td className="pr-2 text-ink-3">Fuel burn + track evolution (γ)</td><td>{fmtCoef(m.lap_effect)} s/lap</td></tr>
              {m.track_temp_effect && <tr><td className="pr-2 text-ink-3">Track temperature</td><td>{fmtCoef(m.track_temp_effect)} s/°C</td></tr>}
              {compounds.map((c) => (
                <tr key={c}>
                  <td className="pr-2 text-ink-3">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: COMPOUND[c] ?? FIELD }} />{c} tyre age (field)
                  </td>
                  <td>{fmtCoef(m.field_tyre_slopes[c])} s/lap</td>
                </tr>
              ))}
              <tr><td className="pr-2 text-ink-3">Fit</td><td>n = {m.n_laps} laps · {m.n_drivers} drivers · R² {m.r2} · residual SD {m.residual_sd} s</td></tr>
            </tbody>
          </table>
          {m.warnings.map((w) => <div key={w} className="text-warn">⚠ {w}</div>)}
          <div>
            <div className="flex items-center gap-1 text-ink"><Badge tier="A" /> Model assumptions</div>
            <ul className="list-disc pl-5 text-ink-3">
              {m.assumptions.map((a) => <li key={a}>{a}</li>)}
              <li>Robust SEs ignore lap-to-lap autocorrelation, so intervals may be too narrow</li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
