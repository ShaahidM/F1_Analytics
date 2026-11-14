"use client";

import { useQuery } from "@tanstack/react-query";
import type { Data } from "plotly.js-dist-min";
import { useMemo, useState } from "react";
import { api, type Fit, type Pattern, type PreservationDriver } from "@/lib/api";
import { DRIVER, LAP_RAMP } from "@/lib/colors";
import { Badge } from "./Badge";
import { CompoundChip } from "./ComparisonPanel";
import { Plot } from "./Plot";

type Slot = { slot: "a" | "b"; driver: number; label: string };
const MIN_STINT_LAPS = 4; // a trend needs a run of laps on one set

// Interpretation labels: text + symbol carry the meaning; the edge colour is only a secondary cue
// (hues chosen outside the driver A/B pair and the reserved status colours).
const PATTERN: Record<Pattern, { text: string; symbol: string; edge: string }> = {
  consistent_with_management: { text: "consistent with management", symbol: "▲", edge: "#199e70" },
  consistent_with_grip_loss: { text: "consistent with grip loss", symbol: "▼", edge: "#c98500" },
  mixed: { text: "mixed signals", symbol: "◆", edge: "#9085e9" },
  no_clear_pattern: { text: "no clear pattern", symbol: "—", edge: "#33332f" },
  insufficient_data: { text: "insufficient data", symbol: "·", edge: "#33332f" },
};

const per10 = (f: Fit | null | undefined) => (f ? { est: f.slope * 10, lo: f.ci_low * 10, hi: f.ci_high * 10 } : null);
const fmt = (v: number, unit: string) => `${v >= 0 ? "+" : ""}${v.toFixed(unit === "g" || unit === "s" ? 2 : 1)}`;

export function PreservationView({ sessionId, slots }: { sessionId: string; slots: Slot[] }) {
  const [includeFlagged, setIncludeFlagged] = useState(true);
  const [indicator, setIndicator] = useState("min_speed_kmh");
  const [zoneId, setZoneId] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["preservation", sessionId, slots.map((s) => s.driver), includeFlagged],
    queryFn: () => api.preservation(sessionId, slots.map((s) => s.driver), includeFlagged),
  });

  const braking = useMemo(() => (q.data?.zones ?? []).filter((z) => z.kind === "braking"), [q.data]);
  const columns = useMemo(() => {
    if (!q.data) return [];
    return slots.flatMap((s) => {
      const d = q.data.drivers[String(s.driver)];
      const stints = [...new Set(d.zone_trends.filter((t) => t.n_laps >= MIN_STINT_LAPS).map((t) => t.stint))].sort((x, y) => x - y);
      return stints.map((st, i) => ({ s, d, stint: st, color: LAP_RAMP[s.slot][Math.min(i, 3)] }));
    });
  }, [q.data, slots]);

  if (q.isLoading) return <div className="p-4 text-sm text-ink-3">Computing corner metrics for every clean lap of both drivers…</div>;
  if (q.isError) return <div className="p-4 text-sm text-warn">{(q.error as Error).message}</div>;
  if (!q.data) return null;
  if (!columns.length)
    return (
      <div className="rounded border border-border bg-surface-1 p-4 text-sm text-ink-2">
        No stint has {MIN_STINT_LAPS}+ clean laps on one tyre set, so behaviour can&apos;t be trended against tyre age here.
        This is normal for qualifying (1–3 push laps per set). Use a race session.
      </div>
    );
  const ind = q.data.indicators;
  const zone = braking.find((z) => z.id === zoneId) ?? braking[0];
  const trendOf = (d: PreservationDriver, stint: number, zid: number) => d.zone_trends.find((t) => t.stint === stint && t.zone_id === zid);

  // Indicator vs tyre age for the selected zone.
  const scatter: Data[] = [];
  for (const c of columns) {
    const pts = c.d.rows.filter((r) => r.zone_id === zone?.id && r.stint === c.stint && r[indicator] !== null);
    scatter.push({ type: "scatter", mode: "markers", name: `${c.s.label} stint ${c.stint}`, x: pts.map((r) => r.tyre_age),
      y: pts.map((r) => r[indicator]), marker: { color: c.color, size: 7, line: { color: DRIVER[c.s.slot], width: 1 } },
      text: pts.map((r) => `${c.s.label} L${r.lap_number}`), hoverinfo: "text+y", legendgroup: `${c.s.slot}${c.stint}` });
    const f = zone ? trendOf(c.d, c.stint, zone.id)?.trends[indicator] : null;
    if (f && pts.length) {
      const xs = pts.map((r) => r.tyre_age);
      const x0 = Math.min(...xs);
      const x1 = Math.max(...xs);
      scatter.push({ type: "scatter", mode: "lines", showlegend: false, x: [x0, x1], y: [f.intercept + f.slope * x0, f.intercept + f.slope * x1],
        line: { color: c.color, width: 2 }, hoverinfo: "skip", legendgroup: `${c.s.slot}${c.stint}` });
    }
  }

  // Where time is lost: zone-time trend per 10 laps of tyre age, per driver-stint.
  const timeBars: Data[] = columns.map((c) => {
    const vals = braking.map((z) => per10(trendOf(c.d, c.stint, z.id)?.trends.time_in_zone_s));
    return {
      type: "bar", name: `${c.s.label} stint ${c.stint}`, x: braking.map((z) => z.label), y: vals.map((v) => v?.est ?? null),
      marker: { color: c.color, line: { color: DRIVER[c.s.slot], width: 1 } },
      error_y: { type: "data", symmetric: false, array: vals.map((v) => (v ? v.hi - v.est : 0)),
        arrayminus: vals.map((v) => (v ? v.est - v.lo : 0)), color: "#8a8984", thickness: 1, width: 3 },
      hovertemplate: "%{x}: %{y:+.3f} s per 10 laps<extra>%{fullData.name}</extra>",
    };
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4 rounded border border-border bg-surface-1 px-3 py-2 text-xs text-ink-2">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeFlagged} onChange={(e) => setIncludeFlagged(e.target.checked)} />
          Include laps flagged for traffic / yellow flags
        </label>
        <span className="text-ink-3">
          Every trend is the change per 10 laps of tyre age within one stint (Theil–Sen, 90% CI). A change counts only if
          its CI excludes zero <b>and</b> it exceeds the measurement resolution over the stint.
        </span>
      </div>

      <section className="overflow-x-auto rounded border border-border bg-surface-1">
        <h3 className="flex items-center gap-2 px-2 pt-2 text-xs font-semibold">
          Behaviour pattern by corner zone and stint <Badge tier="I" note="Rule-based label from the indicator trends; it describes what the data is consistent with, never intent or tyre state" />
        </h3>
        <table className="w-full text-[11px]">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-border">
              <th className="px-2 py-1 font-normal">Zone</th>
              {columns.map((c) => (
                <th key={`${c.s.slot}${c.stint}`} className="px-2 py-1 font-normal">
                  <span className="mr-1 inline-block h-2 w-3 rounded-sm" style={{ background: c.color }} />
                  {c.s.label} stint {c.stint}{" "}
                  <CompoundChip compound={c.d.zone_trends.find((t) => t.stint === c.stint)?.compound ?? null} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {braking.map((z) => (
              <tr key={z.id} className="border-b border-border/60 align-top">
                <td className="px-2 py-1">
                  <button className="font-mono font-semibold text-ink hover:underline" onClick={() => setZoneId(z.id)}>{z.label}</button>
                </td>
                {columns.map((c) => {
                  const t = trendOf(c.d, c.stint, z.id);
                  const p = PATTERN[t?.pattern ?? "insufficient_data"];
                  return (
                    <td key={`${c.s.slot}${c.stint}`} className="px-2 py-1">
                      <div className="border-l-2 pl-2" style={{ borderColor: p.edge }}>
                        <div className="text-ink">{p.symbol} {p.text}</div>
                        {t?.evidence.map((e) => <div key={e} className="text-[10px] text-ink-3">{e}</div>)}
                        {t && <div className="text-[10px] text-ink-3">n = {t.n_laps} laps, ages span {t.tyre_age_span}</div>}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <section className="rounded border border-border bg-surface-1 p-2">
          <div className="flex flex-wrap items-center gap-2 px-1 text-xs">
            <span className="font-semibold">Indicator vs tyre age</span>
            <select value={indicator} onChange={(e) => setIndicator(e.target.value)}>
              {Object.entries(ind).map(([k, v]) => <option key={k} value={k}>{v.label} ({v.unit})</option>)}
            </select>
            <select value={zone?.id ?? ""} onChange={(e) => setZoneId(Number(e.target.value))}>
              {braking.map((z) => <option key={z.id} value={z.id}>{z.label}</option>)}
            </select>
            <Badge tier="C" note={`Increase means: ${ind[indicator]?.increase_means}`} />
          </div>
          <Plot height={340} data={scatter}
            layout={{ xaxis: { title: { text: "Tyre age (laps on set)" } }, yaxis: { title: { text: `${ind[indicator]?.label} (${ind[indicator]?.unit})` } },
              margin: { l: 60, r: 12, t: 16, b: 90 }, legend: { orientation: "h", y: -0.3 } }} />
          <p className="px-1 text-[10px] text-ink-3">
            An increase means {ind[indicator]?.increase_means}. Fuel burn alone makes later laps lighter, so brake points
            tend to move later and speeds rise as a stint goes on; that has to be weighed against any tyre effect.
          </p>
        </section>
        <section className="rounded border border-border bg-surface-1 p-2">
          <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">
            Where time is lost as tyres age <Badge tier="E" note="Theil–Sen slope of time-in-zone vs tyre age × 10, with 90% CI" />
          </h3>
          <Plot height={340} data={timeBars}
            layout={{ barmode: "group", yaxis: { title: { text: "Δ zone time per 10 laps (s)" }, zeroline: true },
              margin: { l: 60, r: 12, t: 16, b: 90 }, legend: { orientation: "h", y: -0.3 } }} />
          <p className="px-1 text-[10px] text-ink-3">
            Positive = the zone gets slower as tyres age (fuel burn alone would make it faster). Whiskers are 90% CIs.
          </p>
        </section>
      </div>

      <section className="overflow-x-auto rounded border border-border bg-surface-1">
        <h3 className="flex items-center gap-2 px-2 pt-2 text-xs font-semibold">
          {ind[indicator]?.label}: change per 10 laps, all zones <Badge tier="E" />
        </h3>
        <table className="w-full text-[11px]">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-border">
              <th className="px-2 py-1 font-normal">Zone</th>
              {columns.map((c) => <th key={`${c.s.slot}${c.stint}`} className="px-2 py-1 font-normal">{c.s.label} stint {c.stint}</th>)}
            </tr>
          </thead>
          <tbody>
            {braking.map((z) => (
              <tr key={z.id} className="border-b border-border/60">
                <td className="px-2 py-1 font-mono font-semibold">{z.label}</td>
                {columns.map((c) => {
                  const t = trendOf(c.d, c.stint, z.id);
                  const v = per10(t?.trends[indicator]);
                  const sig = t?.significant[indicator] ?? 0;
                  return (
                    <td key={`${c.s.slot}${c.stint}`} className={`px-2 py-1 font-mono ${sig ? "font-semibold text-ink" : "text-ink-3"}`}>
                      {v ? `${fmt(v.est, ind[indicator].unit)} [${fmt(v.lo, ind[indicator].unit)}, ${fmt(v.hi, ind[indicator].unit)}]` : "—"}
                      {sig !== 0 && " ●"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="px-2 py-1 text-[10px] text-ink-3">
          ● = counts as a change (CI excludes zero and the change over the stint is at least {ind[indicator]?.min_change}{" "}
          {ind[indicator]?.unit}). Grey values are within noise.
        </p>
      </section>

      <section className="overflow-x-auto rounded border border-border bg-surface-1">
        <h3 className="flex items-center gap-2 px-2 pt-2 text-xs font-semibold">Whole-lap behaviour trends (per 10 laps) <Badge tier="E" /></h3>
        <table className="w-full text-[11px]">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-border">
              <th className="px-2 py-1 font-normal">Driver · stint</th>
              {["full_throttle_pct", "partial_throttle_pct", "coast_m", "braking_time_s", "mean_decel_g", "throttle_ramp_m"].map((k) => (
                <th key={k} className="px-2 py-1 font-normal">{k.replace(/_/g, " ")} <span className="text-ink-3">({q.data!.style_metrics[k]?.unit})</span></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slots.flatMap((s) => q.data!.drivers[String(s.driver)].lap_trends.map((lt) => (
              <tr key={`${s.slot}${lt.stint}`} className="border-b border-border/60">
                <td className="px-2 py-1">
                  <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER[s.slot] }} />
                  {s.label} · stint {lt.stint} <CompoundChip compound={lt.compound} /> <span className="text-ink-3">n={lt.n_laps}</span>
                </td>
                {["full_throttle_pct", "partial_throttle_pct", "coast_m", "braking_time_s", "mean_decel_g", "throttle_ramp_m"].map((k) => {
                  const v = per10(lt.trends[k]);
                  const sig = v && (v.lo > 0 || v.hi < 0);
                  return (
                    <td key={k} className={`px-2 py-1 font-mono ${sig ? "text-ink" : "text-ink-3"}`}>
                      {v ? `${fmt(v.est, "")} [${fmt(v.lo, "")}, ${fmt(v.hi, "")}]` : "—"}
                    </td>
                  );
                })}
              </tr>
            )))}
          </tbody>
        </table>
      </section>

      <section className="rounded border border-border bg-surface-1 px-3 py-2 text-[11px] text-ink-2">
        <div className="mb-1 font-semibold text-ink">Alternative explanations to weigh before reading any pattern as tyre management</div>
        <ul className="list-disc pl-5">
          {q.data.confounders.map((c) => <li key={c}>{c}</li>)}
        </ul>
        <p className="mt-1 text-ink-3">No tyre temperature, pressure, wear or grip measurement exists in public data. Nothing on this page measures tyre state.</p>
      </section>
    </div>
  );
}
