"use client";

import { useQuery } from "@tanstack/react-query";
import type { Data, Layout } from "plotly.js-dist-min";
import { useMemo } from "react";
import { api, type Driver, type PitStop } from "@/lib/api";
import { COMPOUND, DRIVER } from "@/lib/colors";
import { fmtLap } from "@/lib/trace";
import { Badge } from "./Badge";
import { CompoundChip } from "./ComparisonPanel";
import { Plot } from "./Plot";

type Slot = { slot: "a" | "b"; driver: number; label: string };
const UNKNOWN = "#8a8984";
const DASH: Record<string, "solid" | "dash" | "dot" | "dashdot"> = { SOFT: "dot", MEDIUM: "dash", HARD: "solid", INTERMEDIATE: "dashdot", WET: "dashdot" };
const sgn = (v: number | null, d = 2) => (v === null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`);

export function StrategyView({ sessionId, slots, drivers }: { sessionId: string; slots: Slot[]; drivers: Driver[] }) {
  const ids = slots.map((s) => s.driver);
  const q = useQuery({ queryKey: ["strategy", sessionId, ids], queryFn: () => api.strategy(sessionId, ids) });
  const model = useQuery({ queryKey: ["modelB", sessionId, ids, true], queryFn: () => api.model(sessionId, ids, true), retry: false });
  const code = useMemo(() => Object.fromEntries(drivers.map((d) => [d.driver_number, d.code])), [drivers]);
  const slotOf = (d: number) => slots.find((s) => s.driver === d);

  if (q.isLoading) return <div className="p-4 text-sm text-ink-3">Building strategy view…</div>;
  if (q.isError) return <div className="p-4 text-sm text-warn">{(q.error as Error).message}</div>;
  const st = q.data!;

  // 1. Stint timeline for the whole field, finishing order top to bottom.
  const rowLabel = (d: number) => (slotOf(d) ? `▶ ${code[d] ?? d}` : String(code[d] ?? d));
  const timeline: Data[] = st.stints.filter((s) => st.order.includes(s.driver_number)).map((s) => ({
    type: "bar", orientation: "h", base: s.lap_start - 0.5, x: [s.lap_end - s.lap_start + 1], y: [rowLabel(s.driver_number)],
    marker: { color: s.compound ? COMPOUND[s.compound] ?? UNKNOWN : UNKNOWN, line: { color: "#1a1a19", width: 2 } },
    text: [`${s.compound ? s.compound[0] : "?"} ${s.lap_end - s.lap_start + 1}`], textposition: "inside", insidetextanchor: "middle",
    textfont: { color: "#121211", size: 10 }, showlegend: false,
    hovertemplate: `${code[s.driver_number] ?? s.driver_number} stint ${s.stint}: ${s.compound ?? "compound n/a"} L${s.lap_start}–${s.lap_end}` +
      (s.tyre_age_start !== null ? ` · age at start ${s.tyre_age_start}${s.tyre_age_assumed ? " (inferred)" : ""}` : "") + "<extra></extra>",
  }));
  const order = st.order.map(rowLabel);

  // 2/3. Gap and running position for the pair; pit stops as vertical guides, pit cycles shaded.
  const pitShapes: Partial<Layout>["shapes"] = slots.flatMap((s) => (st.pit_stops[String(s.driver)] ?? []).map((p) => ({
    type: "line" as const, x0: p.lap + 0.5, x1: p.lap + 0.5, yref: "paper" as const, y0: 0, y1: 1,
    line: { color: DRIVER[s.slot], width: 1, dash: "dot" as const } })));
  const cycleShapes: Partial<Layout>["shapes"] = st.cycles.map((c) => ({
    type: "rect" as const, x0: c.first_lap - 0.5, x1: c.second_lap + 1.5, yref: "paper" as const, y0: 0, y1: 1,
    fillcolor: "rgba(240,239,236,0.05)", line: { width: 0 } }));
  const [a, b] = slots;

  return (
    <div className="flex flex-col gap-3">
      <section className="rounded border border-border bg-surface-1 p-2">
        <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">Tyre strategy, whole field (finishing order) <Badge tier="M" note="Stints and compounds from the timing feed; 2019–22 stints are inferred from pit stops" /></h3>
        <Plot height={Math.max(260, order.length * 22 + 60)} data={timeline}
          layout={{ barmode: "overlay", xaxis: { title: { text: "Lap" }, range: [0.5, st.total_laps + 0.5] },
            yaxis: { categoryorder: "array", categoryarray: [...order].reverse(), automargin: true, tickfont: { size: 10 } },
            margin: { l: 56, r: 12, t: 8, b: 40 } }} />
        <p className="px-1 text-[10px] text-ink-3">Bars are coloured by compound (S/M/H labelled inside); ▶ marks the two selected drivers.</p>
      </section>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <section className="rounded border border-border bg-surface-1 p-2">
          <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">Gap {b.label} − {a.label} at each lap <Badge tier="C" note={`From ${st.timing_basis}`} /></h3>
          <Plot height={300} data={[{ type: "scatter", mode: "lines+markers", x: st.gap.map((g) => g.lap), y: st.gap.map((g) => g.gap_s),
            line: { color: "#c3c2b7", width: 1.5 }, marker: { size: 3 }, hovertemplate: `L%{x}: ${b.label} %{y:+.2f} s vs ${a.label}<extra></extra>` }]}
            layout={{ xaxis: { title: { text: "Lap" } }, yaxis: { title: { text: `${b.label} behind ${a.label} (s)` }, zeroline: true },
              shapes: [...(pitShapes ?? []), ...(cycleShapes ?? [])], margin: { l: 56, r: 12, t: 8, b: 40 } }} />
          <p className="px-1 text-[10px] text-ink-3">Positive = {b.label} behind. Dotted lines = pit stops ({a.label} blue, {b.label} orange); shaded = paired pit cycles.</p>
        </section>
        <section className="rounded border border-border bg-surface-1 p-2">
          <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">Running position <Badge tier="C" note="Rank of line-crossing time among cars completing each lap" /></h3>
          <Plot height={300} data={slots.map((s) => ({ type: "scatter", mode: "lines", name: s.label, line: { color: DRIVER[s.slot], width: 2, shape: "hv" },
            x: (st.positions[String(s.driver)] ?? []).map((p) => p.lap), y: (st.positions[String(s.driver)] ?? []).map((p) => p.position) }))}
            layout={{ xaxis: { title: { text: "Lap" } }, yaxis: { title: { text: "Position" }, autorange: "reversed", dtick: 1 },
              shapes: pitShapes, margin: { l: 56, r: 12, t: 8, b: 40 }, legend: { orientation: "h", y: -0.25 } }} />
        </section>
      </div>

      <section className="overflow-x-auto rounded border border-border bg-surface-1">
        <h3 className="flex flex-wrap items-center gap-2 px-2 pt-2 text-xs font-semibold">
          Pit stops
          {st.pit_loss_reference && (
            <span className="font-normal text-ink-3">
              · third-party reference loss (MultiViewer): {Object.entries(st.pit_loss_reference).map(([k, v]) => `${k} ${v.toFixed(1)} s`).join(" · ")}
            </span>
          )}
        </h3>
        <table className="w-full text-[11px]">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-border">
              <th className="px-2 py-1 font-normal">Driver · lap</th>
              <th className="px-2 py-1 font-normal">Tyres</th>
              <th className="px-2 py-1 font-normal">Pit-lane time <Badge tier="M" /></th>
              <th className="px-2 py-1 font-normal">Stationary <Badge tier="M" /></th>
              <th className="px-2 py-1 font-normal">In-lap / out-lap <Badge tier="M" /></th>
              <th className="px-2 py-1 font-normal">Baseline lap <Badge tier="C" note="Median of the driver's clean laps within ±5 laps" /></th>
              <th className="px-2 py-1 font-normal">Estimated total loss <Badge tier="E" note="in-lap + out-lap − 2 × baseline; fuel, traffic and tyre state differ between those laps" /></th>
            </tr>
          </thead>
          <tbody>
            {slots.flatMap((s) => (st.pit_stops[String(s.driver)] ?? []).map((p: PitStop) => (
              <tr key={`${s.slot}${p.lap}`} className="border-b border-border/60">
                <td className="px-2 py-1">
                  <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER[s.slot] }} />{s.label} · L{p.lap}
                </td>
                <td className="px-2 py-1">
                  <CompoundChip compound={p.from_compound} /> <span className="text-ink-3">({p.from_tyre_age ?? "?"} laps)</span> → <CompoundChip compound={p.to_compound} />
                </td>
                <td className="px-2 py-1 font-mono">{p.lane_s?.toFixed(2) ?? "—"} s</td>
                <td className="px-2 py-1 font-mono">{p.stationary_s !== null ? `${p.stationary_s.toFixed(2)} s` : "not in feed"}</td>
                <td className="px-2 py-1 font-mono">{fmtLap(p.in_lap_s)} / {fmtLap(p.out_lap_s)}</td>
                <td className="px-2 py-1 font-mono">{fmtLap(p.baseline_lap_s)}</td>
                <td className="px-2 py-1 font-mono">
                  {p.estimated_loss_s?.toFixed(1) ?? "—"} s
                  {p.under_neutralisation && <span className="ml-1 text-warn">under SC/VSC/red: cheaper stop</span>}
                </td>
              </tr>
            )))}
          </tbody>
        </table>
      </section>

      <section className="overflow-x-auto rounded border border-border bg-surface-1">
        <h3 className="flex items-center gap-2 px-2 pt-2 text-xs font-semibold">
          Undercut / overcut: paired pit cycles <Badge tier="C" note="Gaps from timing at the end of the lap before the first stop and the lap after the second stop" />
        </h3>
        {st.cycles.length === 0 ? (
          <p className="px-2 py-2 text-xs text-ink-3">The two drivers never stopped within 6 laps of each other, so there is no direct undercut/overcut to measure. Use the gap chart to compare their strategies.</p>
        ) : (
          <table className="w-full text-[11px]">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-border">
                <th className="px-2 py-1 font-normal">First stopper</th>
                <th className="px-2 py-1 font-normal">Stops</th>
                <th className="px-2 py-1 font-normal">Gap before → after</th>
                <th className="px-2 py-1 font-normal">Net for first stopper</th>
                <th className="px-2 py-1 font-normal">from pit-lane time</th>
                <th className="px-2 py-1 font-normal">from on-track laps</th>
                <th className="px-2 py-1 font-normal">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {st.cycles.map((c) => {
                const f = slotOf(c.first_stopper);
                return (
                  <tr key={`${c.first_lap}-${c.second_lap}`} className="border-b border-border/60">
                    <td className="px-2 py-1">
                      <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: f ? DRIVER[f.slot] : UNKNOWN }} />{f?.label}
                    </td>
                    <td className="px-2 py-1 font-mono">L{c.first_lap} / L{c.second_lap}</td>
                    <td className="px-2 py-1 font-mono">{sgn(c.gap_before_s)} → {sgn(c.gap_after_s)} s</td>
                    <td className="px-2 py-1 font-mono">{c.net_change_s === null ? "—" : `${c.net_change_s <= 0 ? "gained" : "lost"} ${Math.abs(c.net_change_s).toFixed(2)} s`}</td>
                    <td className="px-2 py-1 font-mono">{sgn(c.lane_time_diff_s)} s</td>
                    <td className="px-2 py-1 font-mono">{sgn(c.on_track_diff_s)} s</td>
                    <td className="px-2 py-1">
                      {c.outcome}
                      {c.neutralised && <div className="text-[10px] text-warn">SC/VSC/red during the cycle: not a clean comparison</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="px-2 py-1 text-[10px] text-ink-3">
          Gap = first stopper&apos;s time behind the second stopper (positive = behind). &quot;From on-track laps&quot; mixes the
          fresh-tyre effect with traffic and the second stopper&apos;s old-tyre pace; it is not a pure tyre measurement.
        </p>
      </section>

      <CrossCompound model={model.data} isError={model.isError} error={model.error as Error | null} slots={slots} />
    </div>
  );
}

function CrossCompound({ model, isError, error, slots }: {
  model: Awaited<ReturnType<typeof api.model>> | undefined; isError: boolean; error: Error | null; slots: Slot[];
}) {
  if (isError) return <div className="text-xs text-ink-3">Cross-compound comparison unavailable: {error?.message}</div>;
  if (!model) return <div className="text-xs text-ink-3">Fitting the session-wide model…</div>;
  if (!model.ok) return <div className="text-xs text-warn">Cross-compound comparison unavailable: {model.reason}</div>;
  const data: Data[] = [];
  for (const c of model.pace_curves) {
    const s = slots.find((x) => x.slot === c.tag.toLowerCase())!;
    const color = DRIVER[s.slot];
    const name = `${s.label} · ${c.compound}${c.driver_used_ages ? ` (ran ages ${c.driver_used_ages[0]}–${c.driver_used_ages[1]})` : " (not run)"}`;
    data.push({ type: "scatter", mode: "lines", x: [...c.tyre_age, ...[...c.tyre_age].reverse()], y: [...c.ci_high, ...[...c.ci_low].reverse()],
      fill: "toself", fillcolor: s.slot === "a" ? "rgba(57,135,229,0.10)" : "rgba(217,89,38,0.10)", line: { width: 0 }, hoverinfo: "skip",
      showlegend: false, legendgroup: name });
    data.push({ type: "scatter", mode: "lines", name, x: c.tyre_age, y: c.lap_time, legendgroup: name,
      line: { color, width: 2, dash: DASH[c.compound] ?? "solid" }, hovertemplate: `${name}<br>age %{x}: %{y:.3f} s<extra></extra>` });
  }
  return (
    <section className="rounded border border-border bg-surface-1 p-2">
      <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">
        Cross-compound pace at equal fuel and conditions <Badge tier="E" note="Model B predictions with 90% CI bands" />
      </h3>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Plot height={340} data={data}
          layout={{ xaxis: { title: { text: "Tyre age (laps on set)" } }, yaxis: { title: { text: "Predicted lap time (s)" } },
            margin: { l: 60, r: 12, t: 8, b: 100 }, legend: { orientation: "h", y: -0.3 } }} />
        <div className="text-[11px] text-ink-2">
          <p className="text-ink-3">
            Predicted lap time on each compound as the tyre ages, for each driver, at a common reference point (lap{" "}
            {model.reference.lap_number}{model.reference.track_temp !== null ? `, track ${model.reference.track_temp.toFixed(1)} °C` : ""}), so a
            Medium stint and a Hard stint can be compared without the fuel difference. Line style = compound (solid hard, dashed
            medium, dotted soft). Ages outside a driver&apos;s own run are extrapolated from the field.
          </p>
          <table className="mt-2 w-full font-mono">
            <tbody>
              {Object.entries(model.compound_offsets).map(([c, v]) => (
                <tr key={c}>
                  <td className="pr-2"><CompoundChip compound={c} /></td>
                  <td>{c === model.reference.compound ? "reference" : `${sgn(v.estimate, 3)} s [${sgn(v.ci_low, 3)}, ${sgn(v.ci_high, 3)}] on fresh tyres`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {model.warnings.map((w) => <div key={w} className="mt-1 text-warn">⚠ {w}</div>)}
        </div>
      </div>
    </section>
  );
}
