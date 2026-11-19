"use client";

import { useQuery } from "@tanstack/react-query";
import type { Data } from "plotly.js-dist-min";
import { useState } from "react";
import { api, type StyleRow } from "@/lib/api";
import type { Data as PlotData } from "plotly.js-dist-min";
import { DRIVER } from "@/lib/colors";
import { Badge } from "./Badge";
import { Plot } from "./Plot";

type Slot = { slot: "a" | "b"; driver: number; label: string };

// Grouped as a lap is driven: throttle → braking → corner speeds → shifting.
const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Throttle application", keys: ["full_throttle_pct", "partial_throttle_pct", "throttle_ramp_m", "exit_accel_g"] },
  { title: "Braking & lifting", keys: ["braking_time_s", "braking_pct", "mean_decel_g", "coast_m"] },
  { title: "Corner speeds (mean over braking zones)", keys: ["mean_entry_kmh", "mean_min_kmh", "mean_exit_kmh", "gear_changes"] },
];

const LABELS: Record<string, string> = {
  full_throttle_pct: "Full throttle",
  partial_throttle_pct: "Partial throttle",
  throttle_ramp_m: "Throttle ramp (pickup → full)",
  exit_accel_g: "Exit acceleration",
  braking_time_s: "Braking time",
  braking_pct: "Braking distance share",
  mean_decel_g: "Mean deceleration",
  coast_m: "Coasting",
  mean_entry_kmh: "Entry speed",
  mean_min_kmh: "Minimum speed",
  mean_exit_kmh: "Exit speed",
  gear_changes: "Gear changes",
};

function median(v: number[]) {
  if (!v.length) return null;
  const s = [...v].sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function StyleView({ sessionId, slots }: { sessionId: string; slots: Slot[] }) {
  const [includeFlagged, setIncludeFlagged] = useState(true);
  const [stint, setStint] = useState<Record<"a" | "b", string>>({ a: "all", b: "all" });
  const q = useQuery({
    queryKey: ["style", sessionId, slots.map((s) => s.driver), includeFlagged],
    queryFn: () => api.style(sessionId, slots.map((s) => s.driver), includeFlagged),
  });

  if (q.isLoading) return <div className="p-4 text-sm text-ink-3">Computing style metrics for every clean lap (first run downloads and aligns each lap)…</div>;
  if (q.isError) return <div className="p-4 text-sm text-warn">{(q.error as Error).message}</div>;
  if (!q.data) return null;
  const defs = q.data.definitions;
  const rowsOf = (s: Slot): StyleRow[] =>
    (q.data!.drivers[String(s.driver)] ?? []).filter((r) => stint[s.slot] === "all" || String(r.stint) === stint[s.slot]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4 card px-3 py-2 text-xs text-ink-2">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeFlagged} onChange={(e) => setIncludeFlagged(e.target.checked)} />
          Include laps flagged for traffic / yellow flags
        </label>
        {slots.map((s) => {
          const stints = [...new Set((q.data!.drivers[String(s.driver)] ?? []).map((r) => r.stint))].filter((x) => x !== null);
          return (
            <label key={s.slot} className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER[s.slot] }} />
              {s.label} laps
              <select value={stint[s.slot]} onChange={(e) => setStint({ ...stint, [s.slot]: e.target.value })}>
                <option value="all">all stints</option>
                {stints.map((n) => (
                  <option key={n} value={String(n)}>stint {n}</option>
                ))}
              </select>
              <span className="text-ink-3">n = {rowsOf(s).length}</span>
            </label>
          );
        })}
        <span className="text-ink-3">Each dot is one clean lap; the bar marks the median.</span>
      </div>

      <p className="text-xs text-ink-3">
        Style differences reflect the car and set-up as well as the driver; teammates give the fairest comparison. Values
        come from ~4 Hz telemetry and braking is on/off only (no pressure).
      </p>

      {GROUPS.map((g) => (
        <section key={g.title} className="card p-2">
          <h3 className="px-1 text-xs font-semibold uppercase tracking-wider text-ink-3">{g.title}</h3>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
            {g.keys.map((k) => {
              const data: Data[] = slots.map((s) => {
                const vals = rowsOf(s).map((r) => r[k]).filter((v): v is number => v !== null && v !== undefined);
                return {
                  type: "box", orientation: "h", name: s.label, x: vals, y: vals.map(() => s.label),
                  boxpoints: "all", jitter: 0.5, pointpos: 0, fillcolor: "rgba(0,0,0,0)",
                  line: { color: DRIVER[s.slot], width: 1.5 }, marker: { color: DRIVER[s.slot], size: 5, opacity: 0.7 },
                  hoverinfo: "x",
                };
              });
              const meds = slots.map((s) => median(rowsOf(s).map((r) => r[k]).filter((v): v is number => v !== null && v !== undefined)));
              return (
                <div key={k} className="rounded border border-border/60 p-1">
                  <div className="flex items-center justify-between gap-2 px-1 text-xs">
                    <span className="font-semibold text-ink">{LABELS[k]} <span className="font-normal text-ink-3">{defs[k]?.unit}</span></span>
                    <Badge tier={defs[k]?.tier ?? "C"} note={defs[k]?.note} />
                  </div>
                  <div className="flex gap-3 px-1 font-mono text-xs text-ink-2">
                    {slots.map((s, i) => (
                      <span key={s.slot} className="flex items-center gap-1">
                        <span className="inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER[s.slot] }} />
                        {s.label} {meds[i] === null ? "—" : (meds[i] as number).toFixed(Math.abs(meds[i] as number) < 10 ? 2 : 1)}
                      </span>
                    ))}
                  </div>
                  <Plot height={140} data={data}
                    layout={{ showlegend: false, margin: { l: 44, r: 8, t: 6, b: 24 }, yaxis: { automargin: true } }} />
                </div>
              );
            })}
          </div>
        </section>
      ))}
      <LineSection sessionId={sessionId} slots={slots} includeFlagged={includeFlagged} />
    </div>
  );
}

/** EXPERIMENTAL line-length proxy: race-average extra distance driven per corner zone (tier E). */
function LineSection({ sessionId, slots, includeFlagged }: { sessionId: string; slots: Slot[]; includeFlagged: boolean }) {
  const q = useQuery({
    queryKey: ["line", sessionId, slots.map((s) => s.driver), includeFlagged],
    queryFn: () => api.line(sessionId, slots.map((s) => s.driver), includeFlagged),
    retry: false,
  });
  if (q.isLoading) return <div className="text-xs text-ink-3">Computing line-length proxy…</div>;
  if (!q.data) return null;
  const [a, b] = slots;
  const label = (id: number) => q.data!.zones.find((z) => z.id === id)?.label ?? String(id);
  const rows = q.data.rows.filter((r) => r.diff_m !== null);
  const chart: PlotData[] = [{
    type: "scatter", mode: "markers", orientation: "h", y: rows.map((r) => label(r.zone_id)), x: rows.map((r) => r.diff_m),
    marker: { size: 9, color: rows.map((r) => (r.significant ? ((r.diff_m ?? 0) > 0 ? DRIVER.a : DRIVER.b) : "#8a8984")),
      line: { color: "#1a1a19", width: 2 } },
    error_x: { type: "data", array: rows.map((r) => 1.96 * (r.se_m ?? 0)), color: "#8a8984", thickness: 1, width: 3 },
    hovertemplate: "%{y}: %{x:+.1f} m<extra></extra>",
  }];
  return (
    <section className="card p-2">
      <h3 className="flex flex-wrap items-center gap-2 px-1 text-xs font-semibold">
        Line length through each corner (experimental)
        <Badge tier="E" note="Distance driven from wheel speed minus track distance, averaged over all clean laps; 95% CI" />
      </h3>
      <p className="px-1 text-xs text-ink-3">
        Public positions are snapped to one track line, so the line itself can&apos;t be drawn. Wheel speed still measures how
        far each car really travelled: extra metres through a corner mean <b>a longer line or more tyre slip</b>, and the two
        can&apos;t be separated. Per-lap noise is ~5 m, so only session averages are shown. Coloured = the difference is at
        least 2 standard errors and has the same sign in both halves of the session.
      </p>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Plot height={Math.max(180, rows.length * 30 + 60)} data={chart}
          layout={{ showlegend: false, xaxis: { title: { text: `${a.label} − ${b.label} extra distance (m)` }, zeroline: true },
            yaxis: { autorange: "reversed", automargin: true }, margin: { l: 70, r: 12, t: 8, b: 44 } }} />
        <table className="w-full text-xs">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-border">
              <th className="px-2 py-1 font-normal">Zone</th>
              <th className="px-2 py-1 font-normal">{a.label} (mean ± SE, n)</th>
              <th className="px-2 py-1 font-normal">{b.label}</th>
              <th className="px-2 py-1 font-normal">Difference</th>
              <th className="px-2 py-1 font-normal">1st / 2nd half</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {q.data.rows.map((r) => (
              <tr key={r.zone_id} className={`border-b border-border/60 ${r.significant ? "text-ink" : "text-ink-3"}`}>
                <td className="px-2 py-1 font-semibold">{label(r.zone_id)}</td>
                <td className="px-2 py-1">{r.a ? `${r.a.mean.toFixed(1)} ± ${r.a.se.toFixed(1)} (${r.a.n})` : "—"}</td>
                <td className="px-2 py-1">{r.b ? `${r.b.mean.toFixed(1)} ± ${r.b.se.toFixed(1)} (${r.b.n})` : "—"}</td>
                <td className="px-2 py-1">{r.diff_m === null ? "—" : `${r.diff_m >= 0 ? "+" : ""}${r.diff_m.toFixed(1)} m (z ${r.z?.toFixed(1)})`}</td>
                <td className="px-2 py-1">{r.halves?.map((h) => `${h >= 0 ? "+" : ""}${h.toFixed(1)}`).join(" / ") ?? "—"}{r.replicated ? " ✓" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
