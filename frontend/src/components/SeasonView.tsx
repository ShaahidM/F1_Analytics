"use client";

import { useQuery } from "@tanstack/react-query";
import type { Data } from "plotly.js-dist-min";
import { useMemo, useState } from "react";
import { api, type RaceSummary, type SeasonAggregate } from "@/lib/api";
import { COMPOUND, DRIVER } from "@/lib/colors";
import { useStore } from "@/lib/store";
import { Badge } from "./Badge";
import { CompoundChip } from "./ComparisonPanel";
import { Plot } from "./Plot";
import { Callout, Loading, SectionHeader, Spinner } from "./ui";

type Tier = "M" | "C" | "E" | "I" | "A";
const STYLE_METRICS: { key: string; label: string; unit: string; digits: number }[] = [
  { key: "coast_m", label: "Coasting per lap", unit: "m", digits: 0 },
  { key: "full_throttle_pct", label: "Full throttle", unit: "% of lap", digits: 1 },
  { key: "throttle_ramp_m", label: "Throttle ramp (pickup → full)", unit: "m", digits: 0 },
  { key: "braking_time_s", label: "Braking time per lap", unit: "s", digits: 1 },
  { key: "mean_decel_g", label: "Mean braking deceleration", unit: "g", digits: 2 },
  { key: "exit_accel_g", label: "Exit acceleration", unit: "g", digits: 2 },
  { key: "mean_min_kmh", label: "Mean minimum corner speed", unit: "km/h", digits: 1 },
];
const COND_LABEL = { dry: "Dry", mixed: "Mixed", wet: "Wet", unknown: "?" } as const;
const short = (r: RaceSummary) => (r.location ?? r.meeting_name).replace(" Grand Prix", "");

export function SeasonView() {
  const openSession = useStore((s) => s.openSession);
  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons });
  const full = (seasons.data ?? []).filter((s) => !s.limited);
  const [year, setYear] = useState<number | null>(null);
  const y = year ?? full.find((s) => s.year < new Date().getFullYear())?.year ?? full[0]?.year ?? null;
  const drivers = useQuery({ queryKey: ["seasonDrivers", y], queryFn: () => api.seasonDrivers(y!), enabled: y !== null });
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [run, setRun] = useState<{ year: number; a: string; b: string } | null>(null);
  const [includeWet, setIncludeWet] = useState(false);

  const q = useQuery({
    queryKey: ["season", run, includeWet],
    queryFn: () => api.seasonCompare(run!.year, run!.a, run!.b, includeWet),
    enabled: !!run,
    refetchInterval: (query) => (query.state.data?.state === "running" ? 4000 : false),
    placeholderData: (prev) => prev,
  });
  const races = useMemo(() => (q.data?.races ?? []).filter((r) => r.status === "ok"), [q.data]);
  const counted = races.filter((r) => includeWet || r.conditions === "dry");

  return (
    <div className="flex flex-col gap-5 px-5 py-4">
      <div className="card flex flex-wrap items-end gap-x-5 gap-y-3 p-4">
        <label className="flex flex-col gap-1" data-field="Season">
          <span className="eyebrow">Season</span>
          <select className="w-28" value={y ?? ""} onChange={(e) => { setYear(Number(e.target.value)); setA(""); setB(""); }}>
            {full.map((s) => <option key={s.year} value={s.year}>{s.year}</option>)}
          </select>
        </label>
        {(["a", "b"] as const).map((slot) => (
          <label key={slot} className="flex flex-col gap-1" data-field={`Driver ${slot.toUpperCase()}`}>
            <span className="eyebrow">Driver {slot.toUpperCase()}</span>
            <span className="flex items-center gap-2">
              <span aria-hidden className="h-3 w-3 rounded-sm" style={{ background: DRIVER[slot] }} />
              <select className="w-64" value={slot === "a" ? a : b} disabled={!drivers.data}
                onChange={(e) => (slot === "a" ? setA(e.target.value) : setB(e.target.value))}>
                <option value="">{drivers.isLoading ? "Loading drivers…" : "Select driver"}</option>
                {drivers.data?.map((d) => (
                  <option key={d.code} value={d.code} disabled={d.code === (slot === "a" ? b : a)}>
                    {d.code} · {d.full_name} ({d.teams.join(" / ")}) · {d.races} races
                  </option>
                ))}
              </select>
            </span>
          </label>
        ))}
        <button className="btn btn-primary" disabled={!y || !a || !b || a === b}
          onClick={() => setRun({ year: y!, a, b })}>
          Compare season
        </button>
        <label className="flex items-center gap-1.5 text-xs text-ink-2">
          <input type="checkbox" checked={includeWet} onChange={(e) => setIncludeWet(e.target.checked)} />
          Include wet &amp; mixed races in season figures
        </label>
        <p className="basis-full text-xs text-ink-3">
          Teammates give the fairest comparison: same car, so differences are more about the driver. The first run for a pair
          downloads every race (about 10–15 minutes at OpenF1&apos;s free rate limit); races appear as they finish and are cached.
        </p>
      </div>

      {!run && (
        <Callout title="Season comparison">
          Pick a season and two drivers. Each race is analysed with the same methods as the session view (race-wide tyre
          model, like-for-like pace gap, driving style, behaviour patterns), then summarised across the season.
        </Callout>
      )}
      {run && q.isLoading && <Loading text="Starting season analysis…" />}
      {q.isError && <Callout tone="warn">{(q.error as Error).message}</Callout>}

      {q.data && run && (
        <>
          <Progress data={q.data} />
          {races.length > 0 && (
            <>
              <Scorecard agg={q.data.aggregate} a={run.a} b={run.b} counted={counted.length}
                faster={{ a: counted.filter((r) => (r.pace_gap?.ci_low ?? 0) > 0).length, b: counted.filter((r) => (r.pace_gap?.ci_high ?? 0) < 0).length }} />
              <PaceChart races={races} a={run.a} b={run.b} />
              <TyreChart races={races} a={run.a} b={run.b} />
              <StyleChart races={races} a={run.a} b={run.b} />
              <RaceTable races={q.data.races} a={run.a} b={run.b}
                onOpen={(r) => r.a_number && r.b_number && openSession(run.year, r.session_id, r.a_number, r.b_number)} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function Progress({ data }: { data: { state: string; done?: number; total?: number; current?: string | null; error?: string } }) {
  if (data.state === "done") return null;
  if (data.state === "failed") return <Callout tone="warn" title="Season analysis failed">{data.error}</Callout>;
  const pct = data.total ? Math.round((100 * (data.done ?? 0)) / data.total) : 0;
  return (
    <div className="card flex items-center gap-3 p-3 text-xs text-ink-2" role="status">
      <Spinner />
      <div className="flex-1">
        <div>
          Analysing races: {data.done ?? 0} of {data.total || "…"}
          {data.current ? ` · now ${data.current}` : ""}
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3">
          <div className="h-full rounded-full bg-ink-2 transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}

function Scorecard({ agg, a, b, counted, faster }: {
  agg: SeasonAggregate[]; a: string; b: string; counted: number; faster: { a: number; b: number };
}) {
  const get = (d: string, m: string) => agg.find((r) => r.driver === d && r.metric === m);
  const gap = get(b, "pace_gap_vs_a");
  const tyreMetrics = [...new Set(agg.filter((r) => r.metric.startsWith("tyre_cost_")).map((r) => r.metric))].sort();
  const rows: { label: string; metric: string; unit: string; digits: number; tier: Tier; note: string }[] = [
    ...tyreMetrics.map((m) => ({ label: `Tyre-wear cost, ${m.replace("tyre_cost_", "").toLowerCase()}`, metric: m, unit: "s/lap",
      digits: 3, tier: "E" as Tier, note: "Median across races of the race-wide model's per-driver tyre-age slope" })),
    { label: "Behaviour labelled as management", metric: "management_share", unit: "share", digits: 2, tier: "I",
      note: "Share of decided corner patterns (management vs grip loss) labelled management; interpretation, not intent" },
    ...STYLE_METRICS.map((s) => ({ label: s.label, metric: s.key, unit: s.unit, digits: s.digits, tier: "C" as Tier,
      note: "Median across races of each race's median clean lap" })),
  ];
  return (
    <section>
      <SectionHeader title="Season scorecard"
        description={`Medians across ${counted} race${counted === 1 ? "" : "s"}${counted ? "" : " (none yet)"}. Each value is first summarised per race, then across races, so one unusual race can't dominate.`} />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="card flex flex-col gap-4 p-4">
          <div>
          <div className="eyebrow flex items-center gap-2">Like-for-like race pace <Badge tier="C" note="Median of B − A over laps both drivers completed cleanly on the same lap number (same fuel and track state), per race, then the season median" /></div>
          {gap ? (
            <>
              <div className="mt-1 text-2xl font-semibold tabular-nums">
                {Math.abs(gap.median).toFixed(3)} s
              </div>
              <div className="text-sm text-ink-2">
                per lap, <span style={{ color: gap.median > 0 ? DRIVER.a : DRIVER.b }}>{gap.median > 0 ? a : b}</span> faster (median of {gap.races} races)
              </div>
            </>
          ) : <div className="mt-1 text-sm text-ink-3">Not enough shared clean laps yet.</div>}
          </div>
          <div>
            <div className="eyebrow">Races with a clear pace advantage</div>
            <div className="mt-1.5 flex items-baseline gap-4 text-sm">
              <span><span className="text-xl font-semibold tabular-nums" style={{ color: DRIVER.a }}>{faster.a}</span> {a}</span>
              <span><span className="text-xl font-semibold tabular-nums" style={{ color: DRIVER.b }}>{faster.b}</span> {b}</span>
              <span className="text-ink-3">{counted - faster.a - faster.b} too close to call</span>
            </div>
            <p className="mt-1 text-xs text-ink-3">&ldquo;Clear&rdquo; = the race&apos;s 90% interval excludes zero.</p>
          </div>
        </div>
        <div className="card overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-border">
                <th className="px-3 py-1.5 font-normal">Metric</th>
                <th className="px-3 py-1.5 font-normal"><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER.a }} />{a}</th>
                <th className="px-3 py-1.5 font-normal"><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER.b }} />{b}</th>
                <th className="px-3 py-1.5 font-normal">Races</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const va = get(a, r.metric);
                const vb = get(b, r.metric);
                if (!va && !vb) return null;
                return (
                  <tr key={r.metric} className="border-b border-border/60">
                    <td className="px-3 py-1.5 text-ink-2">{r.label} <span className="text-ink-3">({r.unit})</span> <Badge tier={r.tier} note={r.note} /></td>
                    <td className="px-3 py-1.5 font-mono">{va ? va.median.toFixed(r.digits) : "—"}</td>
                    <td className="px-3 py-1.5 font-mono">{vb ? vb.median.toFixed(r.digits) : "—"}</td>
                    <td className="px-3 py-1.5 font-mono text-ink-3">{Math.max(va?.races ?? 0, vb?.races ?? 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function PaceChart({ races, a, b }: { races: RaceSummary[]; a: string; b: string }) {
  const rs = races.filter((r) => r.pace_gap);
  const data: Data[] = [{
    type: "bar", x: rs.map(short), y: rs.map((r) => r.pace_gap!.median_s),
    marker: { color: rs.map((r) => (r.conditions !== "dry" ? "#5d5c57" : r.pace_gap!.median_s > 0 ? DRIVER.a : DRIVER.b)) },
    error_y: { type: "data", symmetric: false, array: rs.map((r) => r.pace_gap!.ci_high - r.pace_gap!.median_s),
      arrayminus: rs.map((r) => r.pace_gap!.median_s - r.pace_gap!.ci_low), color: "#8a8984", thickness: 1, width: 3 },
    customdata: rs.map((r) => [r.pace_gap!.n_laps, COND_LABEL[r.conditions ?? "unknown"]]),
    hovertemplate: `%{x}: ${b} − ${a} = %{y:+.3f} s/lap<br>%{customdata[0]} shared clean laps · %{customdata[1]}<extra></extra>`,
  }];
  return (
    <section className="card p-3">
      <SectionHeader title="Race pace, race by race"
        description={`Median per-lap gap on laps both drivers completed cleanly on the same lap number. Above zero = ${a} faster, below = ${b} faster; grey = wet or mixed race. Whiskers are 90% bootstrap intervals.`}
        right={<Badge tier="C" />} />
      <Plot height={300} data={data} layout={{ yaxis: { title: { text: `${b} − ${a} (s/lap)` }, zeroline: true }, showlegend: false,
        margin: { l: 60, r: 12, t: 8, b: 70 }, xaxis: { tickangle: -40 } }} />
    </section>
  );
}

function TyreChart({ races, a, b }: { races: RaceSummary[]; a: string; b: string }) {
  const compounds: string[] = [...new Set(races.flatMap((r) => Object.keys(r.model?.a ?? {}).concat(Object.keys(r.model?.b ?? {}))))]
    .filter((c) => c === "SOFT" || c === "MEDIUM" || c === "HARD");
  const [compound, setCompound] = useState("HARD");
  const c = compounds.includes(compound) ? compound : compounds[0];
  const data: Data[] = (["a", "b"] as const).map((tag) => {
    const rs = races.filter((r) => r.model?.[tag]?.[c] && r.conditions === "dry");
    return {
      type: "scatter", mode: "markers", name: tag === "a" ? a : b,
      x: rs.map(short), y: rs.map((r) => r.model![tag][c].estimate),
      error_y: { type: "data", symmetric: false, array: rs.map((r) => r.model![tag][c].ci_high - r.model![tag][c].estimate),
        arrayminus: rs.map((r) => r.model![tag][c].estimate - r.model![tag][c].ci_low), color: DRIVER[tag], thickness: 1, width: 3 },
      marker: { color: DRIVER[tag], size: 8, line: { color: "#1a1a19", width: 2 } },
      offsetgroup: tag, hovertemplate: `%{x}: %{y:+.3f} s/lap<extra>${tag === "a" ? a : b}</extra>`,
    } as Data;
  });
  if (!c) return null;
  return (
    <section className="card p-3">
      <SectionHeader title="Tyre-wear cost, race by race"
        description="How much lap time each extra lap on this compound cost, from each race's race-wide model (fuel burn and track evolution separated). Dry races only. Higher = faster degradation."
        right={
          <span className="flex items-center gap-2">
            <select value={c} onChange={(e) => setCompound(e.target.value)} aria-label="Compound">
              {compounds.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
            <CompoundChip compound={c} />
            <Badge tier="E" note="Race-wide model per-driver tyre-age slope with 90% CI" />
          </span>
        } />
      <Plot height={300} data={data} layout={{ yaxis: { title: { text: "s per lap of tyre age" }, zeroline: true },
        margin: { l: 60, r: 12, t: 8, b: 90 }, legend: { orientation: "h", y: -0.38 }, scattermode: "group",
        xaxis: { tickangle: -40, categoryorder: "array", categoryarray: races.filter((r) => r.conditions === "dry").map(short) } }} />
    </section>
  );
}

function StyleChart({ races, a, b }: { races: RaceSummary[]; a: string; b: string }) {
  const [key, setKey] = useState("coast_m");
  const m = STYLE_METRICS.find((s) => s.key === key)!;
  const rs = races.filter((r) => r.style?.a || r.style?.b);
  const data: Data[] = (["a", "b"] as const).map((tag) => ({
    type: "scatter", mode: "lines+markers", name: tag === "a" ? a : b, x: rs.map(short), y: rs.map((r) => r.style?.[tag]?.[key] ?? null),
    line: { color: DRIVER[tag], width: 2 }, marker: { color: DRIVER[tag], size: 6 },
    hovertemplate: `%{x}: %{y:.${m.digits}f} ${m.unit}<extra>${tag === "a" ? a : b}</extra>`,
  }));
  return (
    <section className="card p-3">
      <SectionHeader title="Driving style through the season"
        description="Each point is the driver's median over that race's clean laps. Style also reflects the car and set-up at each circuit."
        right={
          <span className="flex items-center gap-2">
            <select value={key} onChange={(e) => setKey(e.target.value)} aria-label="Style metric">
              {STYLE_METRICS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <Badge tier="C" />
          </span>
        } />
      <Plot height={280} data={data} layout={{ yaxis: { title: { text: `${m.label} (${m.unit})` } }, margin: { l: 64, r: 12, t: 8, b: 90 },
        xaxis: { tickangle: -40 }, legend: { orientation: "h", y: -0.4 } }} />
    </section>
  );
}

function RaceTable({ races, a, b, onOpen }: { races: RaceSummary[]; a: string; b: string; onOpen: (r: RaceSummary) => void }) {
  const sorted = [...races].sort((x, y) => (x.round ?? 0) - (y.round ?? 0));
  const tyre = (r: RaceSummary, tag: "a" | "b") => {
    const rows = Object.entries(r.model?.[tag] ?? {});
    if (!rows.length) return "—";
    return (
      <span className="flex flex-wrap gap-x-3">
        {rows.map(([c, v]) => (
          <span key={c} className="inline-flex items-center gap-1" title={c}>
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: COMPOUND[c] ?? "#8a8984" }} />
            {c[0]} {v.estimate >= 0 ? "+" : ""}{v.estimate.toFixed(3)}
          </span>
        ))}
      </span>
    );
  };
  const pat = (r: RaceSummary, tag: "a" | "b") => {
    const p = r.patterns?.[tag];
    return p ? `${p.consistent_with_management ?? 0} / ${p.consistent_with_grip_loss ?? 0}` : "—";
  };
  return (
    <section className="card overflow-x-auto">
      <div className="p-3 pb-1">
        <SectionHeader title="Race by race" description="Open any race to explore it in the session view with both drivers selected." />
      </div>
      <table className="w-full text-xs">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-border">
            <th className="px-3 py-1.5 font-normal">Round</th>
            <th className="px-3 py-1.5 font-normal">Conditions</th>
            <th className="px-3 py-1.5 font-normal">Finish {a} / {b}</th>
            <th className="px-3 py-1.5 font-normal">Stops {a} / {b}</th>
            <th className="px-3 py-1.5 font-normal" title={`Median per-lap gap; positive = ${a} faster`}>Pace gap (faster driver)</th>
            <th className="px-3 py-1.5 font-normal" title="Lap time lost per lap of tyre age, per compound">Tyre-wear cost {a} (s/lap)</th>
            <th className="px-3 py-1.5 font-normal">Tyre-wear cost {b} (s/lap)</th>
            <th className="px-3 py-1.5 font-normal" title="Corner zones whose behaviour pattern looks like tyre management / like grip loss">Corners: managing / losing grip {a}</th>
            <th className="px-3 py-1.5 font-normal">Corners: managing / losing grip {b}</th>
            <th className="px-3 py-1.5 font-normal"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.session_id} className="border-b border-border/60 hover:bg-surface-2">
              <td className="px-3 py-1.5"><span className="mr-1 font-mono text-ink-3">R{r.round}</span>{r.meeting_name.replace(" Grand Prix", "")}</td>
              {r.status !== "ok" ? (
                <td colSpan={9} className="px-3 py-1.5 text-ink-3">{r.status === "absent" ? r.message : `Could not analyse: ${r.message}`}</td>
              ) : (
                <>
                  <td className={`px-3 py-1.5 ${r.conditions === "dry" ? "text-ink-2" : "text-warn"}`}>{COND_LABEL[r.conditions ?? "unknown"]}</td>
                  <td className="px-3 py-1.5 font-mono">{r.finish?.a ?? "—"} / {r.finish?.b ?? "—"}</td>
                  <td className="px-3 py-1.5 font-mono">{r.stops?.a} / {r.stops?.b}</td>
                  <td className="px-3 py-1.5 font-mono">
                    {r.pace_gap ? (
                      <span style={{ color: r.pace_gap.median_s >= 0 ? DRIVER.a : DRIVER.b }}>
                        {Math.abs(r.pace_gap.median_s).toFixed(3)} s {r.pace_gap.median_s >= 0 ? a : b}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-3 py-1.5 font-mono">{tyre(r, "a")}</td>
                  <td className="px-3 py-1.5 font-mono">{tyre(r, "b")}</td>
                  <td className="px-3 py-1.5 font-mono">{pat(r, "a")}</td>
                  <td className="px-3 py-1.5 font-mono">{pat(r, "b")}</td>
                  <td className="px-3 py-1.5"><button className="btn whitespace-nowrap py-0.5" onClick={() => onOpen(r)}>Open race</button></td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[11px] text-ink-3">
        Tyre letters: S soft, M medium, H hard, I intermediate, W wet. Finishing positions are line-crossing order (post-race
        penalties not applied) and blank for retirements.
      </p>
    </section>
  );
}
