"use client";

import { useQuery } from "@tanstack/react-query";
import type { Data } from "plotly.js-dist-min";
import { useMemo, useState } from "react";
import { api, type Fit, type Lap, type StintTrend } from "@/lib/api";
import { DRIVER } from "@/lib/colors";
import { fmtLap } from "@/lib/trace";
import { Badge } from "./Badge";
import { CompoundChip } from "./ComparisonPanel";
import { LongRuns } from "./LongRuns";
import { ModelBPanel } from "./ModelBPanel";
import { Plot } from "./Plot";

// Compound is a secondary encoding (marker shape); colour always means driver.
const SYMBOL: Record<string, string> = { SOFT: "circle", MEDIUM: "square", HARD: "diamond", INTERMEDIATE: "triangle-up", WET: "triangle-down" };
const symbolOf = (c: string | null) => (c ? SYMBOL[c] ?? "x" : "circle-open");

type Slot = { slot: "a" | "b"; driver: number; label: string };

function fitText(f: Fit | null | undefined) {
  if (!f) return "—";
  const sig = f.ci_low > 0 || f.ci_high < 0;
  return `${f.slope >= 0 ? "+" : ""}${f.slope.toFixed(3)} s/lap [${f.ci_low.toFixed(3)}, ${f.ci_high.toFixed(3)}]${sig ? "" : " ≈0"}`;
}

export function DegradationView({ sessionId, slots, practice = false }: { sessionId: string; slots: Slot[]; practice?: boolean }) {
  const [includeFlagged, setIncludeFlagged] = useState(true);
  const [fuel, setFuel] = useState(0);
  const drivers = slots.map((s) => s.driver);
  const q = useQuery({
    queryKey: ["degradation", sessionId, drivers, includeFlagged, fuel],
    queryFn: () => api.degradation(sessionId, drivers, includeFlagged, fuel),
    placeholderData: (prev) => prev,
  });

  const slotOf = (d: number) => slots.find((s) => s.driver === d)!;
  const used = (l: Lap) => l.clean && (includeFlagged || l.flags.length === 0);

  const charts = useMemo(() => {
    if (!q.data) return null;
    const { laps, stints } = q.data;
    const byLap: Data[] = [];
    const byAge: Data[] = [];
    const sectors: Record<string, Data[]> = { s1_s: [], s2_s: [], s3_s: [] };
    for (const s of slots) {
      const mine = laps.filter((l) => l.driver_number === s.driver);
      const ok = mine.filter(used);
      const hover = (l: Lap) =>
        `${s.label} L${l.lap_number}<br>${fmtLap(l.lap_time_s)}<br>${l.compound ?? "compound n/a"} · age ${l.tyre_age ?? "?"}` +
        (l.flags.length ? `<br>${l.flags.join(", ")}` : "");
      const marker = (ls: Lap[]) => ({
        color: DRIVER[s.slot],
        symbol: ls.map((l) => (l.flags.length ? `${symbolOf(l.compound)}-open` : symbolOf(l.compound))) as unknown as "circle"[], // Plotly's symbol union omits composed names like "square-open"
        size: 7,
        line: { color: DRIVER[s.slot], width: 1.5 },
      });
      byLap.push({ type: "scatter", mode: "markers", name: `${s.label}`, x: ok.map((l) => l.lap_number), y: ok.map((l) => l.lap_time_s),
        marker: marker(ok), text: ok.map(hover), hoverinfo: "text" });
      byAge.push({ type: "scatter", mode: "markers", name: `${s.label} laps`, x: ok.map((l) => l.tyre_age), y: ok.map((l) => l.lap_time_s),
        marker: marker(ok), text: ok.map(hover), hoverinfo: "text", legendgroup: s.label });
      for (const st of stints.filter((x) => x.driver_number === s.driver)) {
        const f = st.raw_trend;
        if (!f) continue;
        const ages = ok.filter((l) => l.stint === st.stint).map((l) => l.tyre_age ?? 0);
        const x0 = Math.min(...ages);
        const x1 = Math.max(...ages);
        byAge.push({ type: "scatter", mode: "lines", name: `${s.label} stint ${st.stint} ${st.compound ?? ""} ${fitText(f)}`,
          x: [x0, x1], y: [f.intercept + f.slope * x0, f.intercept + f.slope * x1],
          line: { color: DRIVER[s.slot], width: 2, dash: st.stint % 2 ? "solid" : "dash" }, legendgroup: s.label, hoverinfo: "name" });
      }
      for (const key of ["s1_s", "s2_s", "s3_s"] as const) {
        sectors[key].push({ type: "scatter", mode: "markers", name: s.label, x: ok.map((l) => l.tyre_age), y: ok.map((l) => l[key]),
          marker: { ...marker(ok), size: 5 }, hoverinfo: "x+y" });
      }
    }
    // Pit stops as vertical guides on the lap-number chart.
    const pits = laps.filter((l) => l.is_pit_in && drivers.includes(l.driver_number));
    const shapes = pits.map((l) => ({ type: "line" as const, x0: l.lap_number + 0.5, x1: l.lap_number + 0.5, yref: "paper" as const,
      y0: 0, y1: 1, line: { color: DRIVER[slotOf(l.driver_number).slot], width: 1, dash: "dot" as const } }));
    return { byLap, byAge, sectors, shapes };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data, includeFlagged]);

  if (q.isLoading) return <div className="p-4 text-sm text-ink-3">Loading lap data…</div>;
  if (q.isError) return <div className="p-4 text-sm text-warn">{(q.error as Error).message}</div>;
  if (!q.data || !charts) return null;
  const hasSectors = q.data.laps.some((l) => l.s1_s !== null);
  const assumed = q.data.stints.some((s) => s.tyre_age_assumed);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4 card px-3 py-2 text-xs text-ink-2">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeFlagged} onChange={(e) => setIncludeFlagged(e.target.checked)} />
          Include laps flagged for traffic (within 1.5 s of a car or backmarker on track, or being lapped) or yellow flags (hollow markers)
        </label>
        <label className="flex items-center gap-2">
          Fuel-burn correction <Badge tier="A" note="An assumption, not data: lap time gained per lap of fuel burned. Typical published estimates are ~0.03 s/kg × ~1.5–1.8 kg/lap ≈ 0.05–0.06 s/lap" />
          <input type="range" min={0} max={0.1} step={0.005} value={fuel} onChange={(e) => setFuel(Number(e.target.value))} />
          <span className="w-24 font-mono text-ink">{fuel === 0 ? "off" : `${fuel.toFixed(3)} s/lap`}</span>
        </label>
        <span className="text-ink-3">
          {practice
            ? "Long-run laps only: 5+ laps within ±2.5% of the run's median on one tyre set. Push laps, pit laps and red-flag laps are excluded."
            : "Excluded always: SC/VSC/red, pit in/out, lap 1, deleted, outliers (> 5 MAD)."}
        </span>
      </div>

      {assumed && (
        <div className="rounded border border-warn/40 bg-warn/5 px-3 py-1 text-xs text-ink-2">
          ⚠ Tyre age here is <b>inferred</b> from pit stops (assumes a new set at the start and at each stop); compounds are unknown for this season.
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <section className="card p-2">
          <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">Lap time vs lap number <Badge tier="M" /></h3>
          <Plot height={380} data={charts.byLap} layout={{ margin: { l: 56, r: 12, t: 28, b: 110 }, legend: { orientation: "h", y: -0.32 }, xaxis: { title: { text: "Lap" } }, yaxis: { title: { text: "Lap time (s)" } }, shapes: charts.shapes }} />
          <p className="px-1 text-[11px] text-ink-3">Colour = driver, shape = compound (● soft ■ medium ◆ hard ▲ inter ▼ wet). Dotted lines = pit stops.</p>
        </section>
        <section className="card p-2">
          <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">
            Lap time vs tyre age, per-stint trend <Badge tier="E" note={`Theil–Sen robust slope with ${q.data.ci_level * 100}% CI`} />
          </h3>
          <Plot height={380} data={charts.byAge} layout={{ margin: { l: 56, r: 12, t: 28, b: 110 }, legend: { orientation: "h", y: -0.32 }, xaxis: { title: { text: "Tyre age (laps on set)" } }, yaxis: { title: { text: "Lap time (s)" } } }} />
          <p className="px-1 text-[11px] text-ink-3">
            The trend combines tyre degradation, fuel burn and track evolution, which are inseparable within one stint.
            It is a raw pace trend, not tyre wear.
          </p>
        </section>
      </div>

      {hasSectors && (
        <section className="card p-2">
          <h3 className="flex items-center gap-2 px-1 text-xs font-semibold">Sector times vs tyre age <Badge tier="M" /></h3>
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
            {(["s1_s", "s2_s", "s3_s"] as const).map((k, i) => (
              <Plot key={k} height={220} data={charts.sectors[k]}
                layout={{ title: { text: `Sector ${i + 1}`, font: { size: 11 } }, showlegend: false, margin: { l: 48, r: 8, t: 28, b: 32 },
                  xaxis: { title: { text: "Tyre age" } } }} />
            ))}
          </div>
        </section>
      )}

      <StintTable stints={practice ? q.data.stints.filter((s) => s.n_used > 0) : q.data.stints} slots={slots} fuel={fuel} />

      {practice ? (
        <LongRuns sessionId={sessionId} slots={slots} includeFlagged={includeFlagged} />
      ) : (
        <ModelBPanel sessionId={sessionId} slots={slots} includeFlagged={includeFlagged} />
      )}
    </div>
  );
}

function StintTable({ stints, slots, fuel }: { stints: StintTrend[]; slots: Slot[]; fuel: number }) {
  const slotOf = (d: number) => slots.find((s) => s.driver === d)!;
  return (
    <section className="overflow-x-auto card">
      <table className="w-full text-xs">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-border">
            <th className="px-2 py-1 font-normal">Driver · stint</th>
            <th className="px-2 py-1 font-normal">Compound</th>
            <th className="px-2 py-1 font-normal">Laps (used / total)</th>
            <th className="px-2 py-1 font-normal">Tyre age</th>
            <th className="px-2 py-1 font-normal">Raw pace trend <Badge tier="E" note="Theil–Sen slope [CI]; ≈0 = CI includes zero" /></th>
            {fuel > 0 && <th className="px-2 py-1 font-normal">Fuel-corrected trend <Badge tier="A" note={`Assumes ${fuel} s/lap fuel effect`} /></th>}
            <th className="px-2 py-1 font-normal">S1 / S2 / S3 trend (s/lap)</th>
            <th className="px-2 py-1 font-normal">Residual SD</th>
          </tr>
        </thead>
        <tbody>
          {stints.map((st) => {
            const s = slotOf(st.driver_number);
            const thin = !st.raw_trend || st.n_used < 6;
            return (
              <tr key={`${st.driver_number}-${st.stint}`} className="border-b border-border/60">
                <td className="px-2 py-1">
                  <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER[s.slot] }} />
                  {s.label} · stint {st.stint} <span className="text-ink-3">(L{st.lap_start}–{st.lap_end})</span>
                </td>
                <td className="px-2 py-1"><CompoundChip compound={st.compound} /></td>
                <td className="px-2 py-1 font-mono">{st.n_used} / {st.n_laps}</td>
                <td className="px-2 py-1 font-mono">
                  {st.tyre_age_start ?? "?"}→{st.tyre_age_start !== null ? st.tyre_age_start + st.n_laps - 1 : "?"}
                  {st.tyre_age_assumed && <span className="text-warn"> (inferred)</span>}
                </td>
                <td className="px-2 py-1 font-mono">
                  {fitText(st.raw_trend)}
                  {thin && <div className="text-[11px] text-warn">{st.raw_trend ? "few laps: low confidence" : "too few usable laps to fit"}</div>}
                </td>
                {fuel > 0 && <td className="px-2 py-1 font-mono">{fitText(st.fuel_corrected_trend)}</td>}
                <td className="px-2 py-1 font-mono">
                  {(["s1_s", "s2_s", "s3_s"] as const).map((k) => st.sector_trends[k]?.slope?.toFixed(3) ?? "—").join(" / ")}
                </td>
                <td className="px-2 py-1 font-mono">{st.raw_trend ? `${st.raw_trend.residual_sd.toFixed(3)} s` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
