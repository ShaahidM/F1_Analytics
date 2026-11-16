"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import type { Data } from "plotly.js-dist-min";
import { useState } from "react";
import { api, type Interval, type OptResult, type ScenarioIn, type SimResult, type SimStint, type WhatIfModel } from "@/lib/api";
import { COMPOUND, DRIVER } from "@/lib/colors";
import { Badge } from "./Badge";
import { Plot } from "./Plot";
import { Callout, Loading, SectionHeader, Spinner } from "./ui";

type Slot = { slot: "a" | "b"; driver: number; label: string };
type Plans = Record<"a" | "b", SimStint[]>;

const fmtDelta = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)} s`;
const fmtRange = (i: Interval) => `${fmtDelta(i.low)} to ${fmtDelta(i.high)}`;

/** "40-43, 50" → [40, 41, 42, 43, 50] */
function parseLaps(text: string, max: number): number[] {
  const out = new Set<number>();
  for (const part of text.split(",")) {
    const m = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!m) continue;
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    for (let l = Math.min(a, b); l <= Math.max(a, b); l++) if (l >= 2 && l <= max) out.add(l);
  }
  return [...out].sort((x, y) => x - y);
}

/** What-if strategy simulator (Stage A: lap-time maths, no traffic). */
export function StrategySimulator({ sessionId, slots }: { sessionId: string; slots: Slot[] }) {
  const model = useQuery({ queryKey: ["whatifModel", sessionId], queryFn: () => api.whatifModel(sessionId), retry: false });
  if (model.isLoading) return <Loading text="Fitting the race model for the strategy simulator" />;
  if (model.isError) {
    return (
      <Callout title="Strategy simulator unavailable for this session">{(model.error as Error).message}</Callout>
    );
  }
  return <Simulator key={sessionId} sessionId={sessionId} slots={slots} wm={model.data!} />;
}

function Simulator({ sessionId, slots, wm }: { sessionId: string; slots: Slot[]; wm: WhatIfModel }) {
  const actual = (d: number) => wm.actual[String(d)] ?? [];
  const [plans, setPlans] = useState<Plans>({ a: actual(slots[0].driver), b: actual(slots[1].driver) });
  const [scText, setScText] = useState("");
  const [vscText, setVscText] = useState("");
  const scenario: ScenarioIn = { sc: parseLaps(scText, wm.total_laps), vsc: parseLaps(vscText, wm.total_laps) };
  const compounds = Object.keys(wm.model.compounds);
  const finishers = new Set(Object.keys(wm.actual));

  const sim = useMutation({
    mutationFn: () => api.simulate(sessionId, slots.map((s) => ({ driver: s.driver, stints: plans[s.slot] })), scenario),
  });
  const [optSlot, setOptSlot] = useState<"a" | "b">("b");
  const [maxStops, setMaxStops] = useState(2);
  const opt = useMutation({ mutationFn: () => api.optimise(sessionId, slots.find((s) => s.slot === optSlot)!.driver, maxStops, scenario) });

  const missing = slots.filter((s) => !finishers.has(String(s.driver)) || !actual(s.driver).length);
  const bt = wm.backtest;

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader
        title="What-if strategy simulator"
        description="Change either driver's stops and tyres and see how their race would likely have finished. Each what-if is the real race plus the modelled difference, so the real strategy reproduces the real result exactly."
        right={
          <span className="flex items-center gap-2 text-[11px] text-ink-3">
            <Badge tier="E" note="Race-wide lap-time model + Monte Carlo (2,000 draws)" />
            {bt.median_abs_error_s !== null && (
              <span title={Object.entries(bt.errors_s).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}s`).join(" · ")}>
                Model accuracy here: median error {bt.median_abs_error_s.toFixed(1)} s over {bt.n_drivers} drivers&apos; real strategies
              </span>
            )}
          </span>
        }
      />
      {missing.length > 0 && (
        <Callout tone="warn">
          {missing.map((s) => s.label).join(" and ")} didn&apos;t complete the full race distance, so they can&apos;t be simulated. Pick
          drivers who finished on the lead lap.
        </Callout>
      )}

      {missing.length === 0 && (
        <>
          <div className="card flex flex-col gap-3 p-3">
            {slots.map((s) => {
              const other = slots.find((o) => o.slot !== s.slot)!;
              return (
                <PlanEditor key={s.slot} slot={s} total={wm.total_laps} compounds={compounds} plan={plans[s.slot]}
                  onChange={(p) => setPlans({ ...plans, [s.slot]: p })}
                  presets={[
                    { label: "Actual", plan: actual(s.driver) },
                    { label: `${other.label}'s strategy`, plan: actual(other.driver).map((x) => ({ ...x })) },
                  ]}
                  unreliable={wm.model.compounds} />
              );
            })}
            <div className="flex flex-wrap items-end gap-4 border-t border-border pt-3 text-xs">
              <label className="flex flex-col gap-1">
                <span className="eyebrow">Safety car on laps</span>
                <input type="text" className="w-40" placeholder="e.g. 40-43" value={scText} onChange={(e) => setScText(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="eyebrow">VSC on laps</span>
                <input type="text" className="w-40" placeholder="e.g. 25-26" value={vscText} onChange={(e) => setVscText(e.target.value)} />
              </label>
              <span className="pb-1.5 text-ink-3">
                {wm.neutralised_laps.length ? `Real neutralised laps (kept as they were): ${wm.neutralised_laps.join(", ")}.` : "No safety cars in the real race."}
              </span>
              <button className="btn btn-primary ml-auto" onClick={() => sim.mutate()} disabled={sim.isPending}>
                {sim.isPending && <Spinner size={12} />} Simulate
              </button>
            </div>
          </div>

          {sim.isError && <Callout tone="warn">{(sim.error as Error).message}</Callout>}
          {sim.data && <SimResults result={sim.data} slots={slots} />}

          <div className="card flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-end gap-3 text-xs">
              <div>
                <div className="text-sm font-semibold text-ink">Best-strategy finder</div>
                <p className="text-ink-3">Tries every 1- to {maxStops}-stop plan on new tyres (stints of 5+ laps, at least two dry compounds, using the safety-car laps above) and ranks them.</p>
              </div>
              <label className="flex flex-col gap-1">
                <span className="eyebrow">Driver</span>
                <select value={optSlot} onChange={(e) => setOptSlot(e.target.value as "a" | "b")}>
                  {slots.map((s) => <option key={s.slot} value={s.slot}>{s.label}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="eyebrow">Up to</span>
                <select value={maxStops} onChange={(e) => setMaxStops(Number(e.target.value))}>
                  {[1, 2, 3].map((n) => <option key={n} value={n}>{n} stop{n > 1 ? "s" : ""}</option>)}
                </select>
              </label>
              <button className="btn" onClick={() => opt.mutate()} disabled={opt.isPending}>
                {opt.isPending && <Spinner size={12} />} Find best strategies
              </button>
            </div>
            {opt.isError && <Callout tone="warn">{(opt.error as Error).message}</Callout>}
            {opt.data && (
              <OptTable result={opt.data} onLoad={(p) => setPlans({ ...plans, [optSlot]: p })} />
            )}
          </div>
        </>
      )}
    </section>
  );
}

function StintBar({ plan, total }: { plan: SimStint[]; total: number }) {
  return (
    <div className="flex h-6 w-full overflow-hidden rounded-md border border-border" aria-hidden>
      {plan.map((s, i) => (
        <div key={i} className="flex items-center justify-center border-r-2 border-surface-1 text-[10px] font-medium text-bg last:border-r-0"
          style={{ width: `${(100 * s.laps) / total}%`, background: COMPOUND[s.compound] ?? "#8a8984" }}>
          {s.laps >= 4 ? `${s.compound[0]} ${s.laps}` : ""}
        </div>
      ))}
    </div>
  );
}

function PlanEditor({ slot, total, compounds, plan, onChange, presets, unreliable }: {
  slot: Slot; total: number; compounds: string[]; plan: SimStint[]; onChange: (p: SimStint[]) => void;
  presets: { label: string; plan: SimStint[] }[]; unreliable: WhatIfModel["model"]["compounds"];
}) {
  const sum = plan.reduce((t, s) => t + s.laps, 0);
  const stops = plan.slice(0, -1).reduce<number[]>((acc, s) => [...acc, (acc.at(-1) ?? 0) + s.laps], []);
  const set = (i: number, patch: Partial<SimStint>) => onChange(plan.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const addStop = () => {
    const last = plan.at(-1)!;
    if (last.laps < 10) return;
    const half = Math.floor(last.laps / 2);
    const next = compounds.find((c) => c !== last.compound && !unreliable[c]?.unreliable) ?? last.compound;
    onChange([...plan.slice(0, -1), { ...last, laps: last.laps - half }, { compound: next, laps: half, start_age: 0 }]);
  };
  const removeStint = (i: number) => {
    if (plan.length < 2) return;
    const merged = plan.filter((_, j) => j !== i);
    const target = Math.max(0, i - 1);
    merged[target] = { ...merged[target], laps: merged[target].laps + plan[i].laps };
    onChange(merged);
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="flex items-center gap-1.5 font-semibold text-ink">
          <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: DRIVER[slot.slot] }} />{slot.label}
        </span>
        <span className={`font-mono ${sum === total ? "text-ink-3" : "text-warn"}`}>{sum}/{total} laps</span>
        <span className="text-ink-3">{plan.length - 1} stop{plan.length === 2 ? "" : "s"}{stops.length ? ` (in-laps ${stops.join(", ")})` : ""}</span>
        <span className="ml-auto flex gap-1">
          {presets.map((p) => (
            <button key={p.label} className="btn py-0.5" onClick={() => onChange(p.plan.map((x) => ({ ...x })))}>{p.label}</button>
          ))}
          <button className="btn py-0.5" onClick={addStop} disabled={(plan.at(-1)?.laps ?? 0) < 10}>+ stop</button>
        </span>
      </div>
      <StintBar plan={plan} total={total} />
      <div className="flex flex-wrap gap-2">
        {plan.map((s, i) => (
          <div key={i} className="flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs">
            <span className="text-ink-3">Stint {i + 1}</span>
            <select aria-label={`${slot.label} stint ${i + 1} compound`} value={s.compound} onChange={(e) => set(i, { compound: e.target.value })}>
              {compounds.map((c) => <option key={c} value={c}>{c}{unreliable[c]?.unreliable ? " (low data)" : ""}</option>)}
            </select>
            <input aria-label={`${slot.label} stint ${i + 1} laps`} type="number" min={1} max={total} className="w-16" value={s.laps}
              onChange={(e) => set(i, { laps: Math.max(1, Number(e.target.value) || 1) })} />
            <span className="text-ink-3">laps</span>
            <label className="flex items-center gap-1 text-ink-3" title="Tyre age at the start of the stint (0 = new set)">
              age
              <input type="number" min={0} className="w-12" value={s.start_age} onChange={(e) => set(i, { start_age: Math.max(0, Number(e.target.value) || 0) })} />
            </label>
            {plan.length > 1 && (
              <button className="text-ink-3 hover:text-ink" aria-label={`Remove stint ${i + 1}`} onClick={() => removeStint(i)}>×</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SimResults({ result, slots }: { result: SimResult; slots: Slot[] }) {
  const gap = result.gap_by_lap;
  const [a, b] = slots;
  const laps = gap ? gap.median.map((_, i) => i + 1) : [];
  const chart: Data[] = gap ? [
    { type: "scatter", mode: "lines", x: [...laps, ...[...laps].reverse()], y: [...gap.high, ...[...gap.low].reverse()],
      fill: "toself", fillcolor: "rgba(195,194,183,0.12)", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { type: "scatter", mode: "lines", name: "What-if (median)", x: laps, y: gap.median, line: { color: "#f0efec", width: 2 } },
    { type: "scatter", mode: "lines", name: "What really happened", x: laps, y: gap.actual, line: { color: "#8a8984", width: 1.5, dash: "dash" } },
  ] : [];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {slots.map((s) => {
          const r = result.drivers[String(s.driver)];
          if (!r) return null;
          const dist = Object.entries(r.position.distribution).sort((x, y) => y[1] - x[1]).slice(0, 3);
          return (
            <div key={s.slot} className="card p-3 text-xs">
              <div className="flex items-center gap-1.5 text-sm font-semibold">
                <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: DRIVER[s.slot] }} />{s.label}
              </div>
              <div className="mt-2 eyebrow">Race time vs their real strategy</div>
              <div className="text-xl font-semibold tabular-nums">{fmtDelta(r.delta_vs_actual_strategy.median)}</div>
              <div className="text-ink-3">90% range {fmtRange(r.delta_vs_actual_strategy)} · negative = faster</div>
              <div className="mt-2 eyebrow">Likely finishing position</div>
              <div className="text-ink-2">
                {dist.map(([p, v]) => `P${p} ${Math.round(v * 100)}%`).join(" · ")} <span className="text-ink-3">(really P{r.position.actual})</span>
              </div>
              {[...r.warnings, ...r.extrapolation].length > 0 && (
                <ul className="mt-2 space-y-1 text-[11px] text-warn">
                  {[...r.warnings, ...r.extrapolation].map((w) => <li key={w}>⚠ {w}</li>)}
                </ul>
              )}
            </div>
          );
        })}
        {result.p_first_ahead !== undefined && (
          <div className="card p-3 text-xs">
            <div className="text-sm font-semibold">Head to head</div>
            <div className="mt-2 eyebrow">Chance {a.label} finishes ahead of {b.label}</div>
            <div className="text-xl font-semibold tabular-nums">{Math.round(result.p_first_ahead * 100)}%</div>
            {gap && (
              <div className="text-ink-3">
                Final gap: {b.label} {gap.median.at(-1)! >= 0 ? "behind" : "ahead"} by {Math.abs(gap.median.at(-1)!).toFixed(1)} s
                (really {Math.abs(gap.actual.at(-1)!).toFixed(1)} s {gap.actual.at(-1)! >= 0 ? "behind" : "ahead"})
              </div>
            )}
          </div>
        )}
      </div>
      {gap && (
        <div className="card p-3">
          <SectionHeader title={`Gap ${b.label} − ${a.label}, lap by lap`}
            description="Positive = second driver behind. The band is the 90% range of the what-if; dashed is the real race." right={<Badge tier="E" />} />
          <Plot height={280} data={chart} layout={{ xaxis: { title: { text: "Lap" } }, yaxis: { title: { text: "Gap (s)" }, zeroline: true },
            margin: { l: 56, r: 12, t: 8, b: 60 }, legend: { orientation: "h", y: -0.3 } }} />
        </div>
      )}
      <div className="card p-3 text-[11px] text-ink-2">
        <div className="mb-1 flex items-center gap-1 font-semibold text-ink"><Badge tier="A" /> Assumptions in this simulation</div>
        <ul className="list-disc space-y-0.5 pl-5 text-ink-3">
          {result.assumptions.map((x) => <li key={x}>{x}</li>)}
        </ul>
      </div>
    </div>
  );
}

function OptTable({ result, onLoad }: { result: OptResult; onLoad: (p: SimStint[]) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-border">
            <th className="px-2 py-1 font-normal">#</th>
            <th className="px-2 py-1 font-normal">Plan for {result.code}</th>
            <th className="px-2 py-1 font-normal">vs real strategy <Badge tier="E" /></th>
            <th className="px-2 py-1 font-normal">90% range</th>
            <th className="px-2 py-1 font-normal">Caveats</th>
            <th className="px-2 py-1 font-normal"></th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-border/60 text-ink-3">
            <td className="px-2 py-1">real</td>
            <td className="px-2 py-1"><StintBar plan={result.actual} total={result.actual.reduce((t, s) => t + s.laps, 0)} /></td>
            <td className="px-2 py-1 font-mono">±0.0 s</td><td></td><td></td><td></td>
          </tr>
          {result.plans.map((p, i) => (
            <tr key={i} className="border-b border-border/60">
              <td className="px-2 py-1 font-mono">{i + 1}</td>
              <td className="w-1/3 px-2 py-1"><StintBar plan={p.stints} total={p.stints.reduce((t, s) => t + s.laps, 0)} /></td>
              <td className="px-2 py-1 font-mono">{fmtDelta(p.delta_vs_actual_strategy.median)}</td>
              <td className="px-2 py-1 font-mono text-ink-3">{fmtRange(p.delta_vs_actual_strategy)}</td>
              <td className="px-2 py-1 text-warn" title={p.extrapolation.join("\n")}>{p.extrapolation.length ? `⚠ ${p.extrapolation.length} extrapolation${p.extrapolation.length > 1 ? "s" : ""}` : ""}</td>
              <td className="px-2 py-1"><button className="btn py-0.5" onClick={() => onLoad(p.stints)}>Load into builder</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[10px] text-ink-3">Hover a caveat to see which stints run beyond the tyre ages seen in this race.</p>
    </div>
  );
}
