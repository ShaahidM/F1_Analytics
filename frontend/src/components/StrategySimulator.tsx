"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import type { Data, Shape } from "plotly.js-dist-min";
import { useEffect, useState } from "react";
import { api, type Interval, type OptResult, type ScenarioIn, type SimDriver, type SimResult, type SimStint, type WhatIfModel } from "@/lib/api";
import { COMPOUND, DRIVER } from "@/lib/colors";
import { Badge } from "./Badge";
import { Plot } from "./Plot";
import { Callout, Loading, Segmented, Spinner } from "./ui";

type Slot = { slot: "a" | "b"; driver: number; label: string };
type Plans = Record<"a" | "b", SimStint[]>;
type Run = { plans: Plans; scenario: ScenarioIn; traffic: boolean };

const fmtDelta = (v: number) => `${v > 0.05 ? "+" : v < -0.05 ? "−" : "±"}${Math.abs(v).toFixed(1)} s`;
const fmtRange = (i: Interval) => `${fmtDelta(i.low)} to ${fmtDelta(i.high)}`;
const sumLaps = (plan: SimStint[]) => plan.reduce((t, s) => t + s.laps, 0);
const samePlan = (x: SimStint[], y: SimStint[]) => JSON.stringify(x) === JSON.stringify(y);
const pitLaps = (plan: SimStint[]) => plan.slice(0, -1).reduce<number[]>((acc, s) => [...acc, (acc.at(-1) ?? 0) + s.laps], []);
const stopsText = (plan: SimStint[]) => {
  const pits = pitLaps(plan);
  if (!pits.length) return "No stops";
  return `${pits.length} stop${pits.length > 1 ? "s" : ""} · pits on lap${pits.length > 1 ? "s" : ""} ${pits.join(", ")}`;
};
// Light compounds (medium, hard, inter) need dark text; soft and wet need light text.
const onCompound = (c: string) => (c === "SOFT" || c === "WET" ? "#f0efec" : "#121211");

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

/** [40, 41, 42, 50] → [[40, 42], [50, 50]] */
function toRanges(laps: number[]): [number, number][] {
  const out: [number, number][] = [];
  for (const l of laps) {
    const last = out.at(-1);
    if (last && l === last[1] + 1) last[1] = l;
    else out.push([l, l]);
  }
  return out;
}
const rangesText = (laps: number[]) => toRanges(laps).map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");

/** What-if strategy simulator: build a strategy per driver, set race conditions, run, read the outcome. */
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

function Step({ n, title, hint, right }: { n: number; title: string; hint?: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="flex items-start gap-2.5">
        <span aria-hidden className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[11px] font-semibold text-ink-2">{n}</span>
        <div>
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {hint && <p className="text-xs text-ink-3">{hint}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}

function Simulator({ sessionId, slots, wm }: { sessionId: string; slots: Slot[]; wm: WhatIfModel }) {
  const actual = (d: number) => wm.actual[String(d)] ?? [];
  const [plans, setPlans] = useState<Plans>({ a: actual(slots[0].driver), b: actual(slots[1].driver) });
  const [scText, setScText] = useState("");
  const [vscText, setVscText] = useState("");
  const [traffic, setTraffic] = useState(true);
  const scenario: ScenarioIn = { sc: parseLaps(scText, wm.total_laps), vsc: parseLaps(vscText, wm.total_laps) };
  const compounds = Object.keys(wm.model.compounds);
  const finishers = new Set(Object.keys(wm.actual));

  const sim = useMutation({
    mutationFn: (run: Run) => api.simulate(sessionId, slots.map((s) => ({ driver: s.driver, stints: run.plans[s.slot] })), run.scenario, run.traffic),
  });
  const current: Run = { plans, scenario, traffic };
  const stale = !!sim.data && !!sim.variables && JSON.stringify(sim.variables) !== JSON.stringify(current);

  const missing = slots.filter((s) => !finishers.has(String(s.driver)) || !actual(s.driver).length);
  const badLaps = slots.filter((s) => sumLaps(plans[s.slot]) !== wm.total_laps);
  const bt = wm.backtest;
  const ov = wm.overtaking;

  return (
    <section className="flex flex-col gap-3" data-shot="whatif">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink">What-if strategy simulator</h2>
          <p className="max-w-3xl text-xs text-ink-3">
            Change either driver&apos;s pit stops and tyres and see how their race would probably have ended. Every what-if
            starts from the real race and adds the modelled difference, so the real strategy reproduces the real result.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3">
          <Badge tier="E" note="Race-wide lap-time model + Monte Carlo (2,000 draws)" />
          {bt.median_abs_error_s !== null && (
            <span className="rounded-md border border-border px-2 py-1"
              title={`Backtest: each driver's real strategy predicted from the model alone.\n${Object.entries(bt.errors_s).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v} s`).join(" · ")}`}>
              Typical model error here: <span className="font-medium text-ink-2">{bt.median_abs_error_s.toFixed(1)} s</span> over a race ({bt.n_drivers} drivers checked)
            </span>
          )}
        </div>
      </div>

      {missing.length > 0 && (
        <Callout tone="warn">
          {missing.map((s) => s.label).join(" and ")} didn&apos;t complete the full race distance, so they can&apos;t be simulated. Pick
          drivers who finished on the lead lap.
        </Callout>
      )}

      {missing.length === 0 && (
        <>
          <div className="card flex flex-col gap-4 p-4" id="whatif-plans">
            <Step n={1} title="Choose each driver's strategy"
              hint="Start from the real strategy or copy the other driver's, then use the arrows to change tyres and pit laps." />
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {slots.map((s) => {
              const other = slots.find((o) => o.slot !== s.slot)!;
              return (
                <PlanEditor key={s.slot} slot={s} total={wm.total_laps} compounds={compounds} plan={plans[s.slot]}
                  isActual={samePlan(plans[s.slot], actual(s.driver))}
                  onChange={(p) => setPlans({ ...plans, [s.slot]: p })}
                  presets={[
                    { label: "Real strategy", plan: actual(s.driver) },
                    { label: `Copy ${other.label}'s`, plan: actual(other.driver) },
                  ]}
                  unreliable={wm.model.compounds} />
              );
            })}
            </div>
          </div>

          <div className="card flex flex-col gap-4 p-4">
            <Step n={2} title="Set the race conditions" hint="Optional. Add neutralisations that didn't happen, and choose whether other cars can get in the way." />
            <div className="grid grid-cols-1 gap-4 md:grid-cols-[auto_auto_1fr]">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ink-2">Add a safety car on laps</span>
                <input type="text" className="w-44" placeholder="e.g. 40-43" value={scText} onChange={(e) => setScText(e.target.value)} />
                <span className="text-[11px] text-ink-3">{scenario.sc.length ? `Laps ${rangesText(scenario.sc)}` : "None"}</span>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ink-2">Add a virtual safety car on laps</span>
                <input type="text" className="w-44" placeholder="e.g. 25-26" value={vscText} onChange={(e) => setVscText(e.target.value)} />
                <span className="text-[11px] text-ink-3">{scenario.vsc.length ? `Laps ${rangesText(scenario.vsc)}` : "None"}</span>
              </label>
              <div className="flex flex-col items-start gap-1">
                <span className="text-xs font-medium text-ink-2">Other cars</span>
                <Segmented label="Traffic" value={traffic ? "traffic" : "clean"} onChange={(v) => setTraffic(v === "traffic")}
                  options={[{ id: "traffic", label: "Traffic & overtaking" }, { id: "clean", label: "Clean air" }]} />
                <span className="text-[11px] text-ink-3">
                  {traffic
                    ? "The driver can be held up by the real field and has to pass to get by."
                    : "Nobody gets in the way: a pure lap-time comparison."}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1 rounded-md bg-surface-2 px-3 py-2 text-xs text-ink-3">
              <span>
                <span className="text-ink-2">In the real race: </span>
                {wm.neutralised_laps.length ? `neutralised on laps ${rangesText(wm.neutralised_laps)} (kept as they were)` : "no safety cars"}
              </span>
              <span>
                <span className="text-ink-2">Overtaking here: </span>
                {ov.n_passes} passes in {ov.n_battles} close battles
                {ov.advantage_for_50pct_s !== null ? `; a car needed ~${ov.advantage_for_50pct_s.toFixed(1)} s/lap more pace for a 50% chance to pass` : ""}
              </span>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border pt-3">
              {badLaps.length > 0 && (
                <span className="text-xs text-warn">
                  {badLaps.map((s) => `${s.label}'s stints add up to ${sumLaps(plans[s.slot])} of ${wm.total_laps} laps`).join("; ")}
                </span>
              )}
              <button className="btn btn-primary px-4 py-2 text-sm" onClick={() => sim.mutate(current)} disabled={sim.isPending || badLaps.length > 0}>
                {sim.isPending && <Spinner size={12} />} {sim.data ? "Run again" : "Run simulation"}
              </button>
            </div>
          </div>

          {sim.isError && <Callout tone="warn">{(sim.error as Error).message}</Callout>}
          {sim.data && sim.variables && (
            <div className="flex flex-col gap-3">
              <Step n={3} title="Results" hint={sim.data.mode === "traffic" ? "With traffic and overtaking" : "Clean air, no traffic"} />
              {stale && (
                <Callout tone="warn" title="These results are out of date">
                  You changed the strategies or race conditions after this run. Press &ldquo;Run again&rdquo; to update them.
                </Callout>
              )}
              <div className={stale ? "opacity-50 transition-opacity" : "transition-opacity"}>
                <SimResults result={sim.data} run={sim.variables} slots={slots} actual={actual} />
              </div>
            </div>
          )}

          <Optimiser sessionId={sessionId} slots={slots} scenario={scenario} traffic={traffic}
            onLoad={(slot, p) => {
              setPlans({ ...plans, [slot]: p });
              document.getElementById("whatif-plans")?.scrollIntoView({ behavior: "smooth", block: "start" });
            }} />
        </>
      )}
    </section>
  );
}

/** Stints as coloured blocks (used in the best-strategy table). */
function StintBar({ plan, total }: { plan: SimStint[]; total: number }) {
  const span = Math.max(total, sumLaps(plan));
  return (
    <div className="flex h-7 w-full overflow-hidden rounded-md bg-surface-3" aria-hidden>
      {plan.map((s, i) => {
        const share = s.laps / span;
        return (
          <div key={i} className="flex items-center justify-center overflow-hidden whitespace-nowrap border-r-2 border-surface-1 text-[11px] font-semibold last:border-r-0"
            style={{ width: `${100 * share}%`, background: COMPOUND[s.compound] ?? "#8a8984", color: onCompound(s.compound) }}
            title={`${s.compound}, ${s.laps} laps`}>
            {share >= 0.2 ? `${s.compound} · ${s.laps} laps` : share >= 0.07 ? `${s.compound[0]} ${s.laps}` : ""}
          </div>
        );
      })}
    </div>
  );
}

/** The compound's initial inside a ring in the compound colour. */
function CompoundBadge({ compound, size = 22 }: { compound: string; size?: number }) {
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full bg-bg font-bold leading-none text-ink"
      style={{ width: size, height: size, border: `3px solid ${COMPOUND[compound] ?? "#8a8984"}`, fontSize: Math.round(size * 0.42) }}>
      {compound[0]}
    </span>
  );
}

const ARROW = "flex h-full items-center px-2 text-base leading-none text-ink-3 hover:text-ink disabled:cursor-not-allowed disabled:opacity-25";

/** ‹ value ›: the arrows step by one; the number can also be typed (applied on Enter or when leaving the field). */
function Stepper({ value, min, max, onChange, label, prefix, suffix }: {
  value: number; min: number; max: number; onChange: (v: number) => void; label: string; prefix?: string; suffix?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null && draft.trim() !== "" && Number.isFinite(Number(draft))) onChange(Math.min(max, Math.max(min, Math.round(Number(draft)))));
    setDraft(null);
  };
  return (
    <div className="flex h-8 items-center justify-between rounded-md border border-border bg-surface-2">
      <button className={ARROW} aria-label={`${label}: down`} disabled={value <= min} onClick={() => onChange(value - 1)}>‹</button>
      <span className="flex items-baseline gap-1 text-xs font-medium">
        {prefix && <span className="text-ink-3">{prefix}</span>}
        <input aria-label={label} inputMode="numeric" value={draft ?? String(value)}
          className="w-8 border-0! bg-transparent! p-0! text-center text-xs! font-semibold"
          onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
        {suffix && <span className="text-ink-3">{suffix}</span>}
      </span>
      <button className={ARROW} aria-label={`${label}: up`} disabled={value >= max} onClick={() => onChange(value + 1)}>›</button>
    </div>
  );
}

/** ‹ (S) SOFT ›: the arrows cycle through the compounds the race model knows. */
function CompoundPicker({ value, options, onChange, label, lowData }: {
  value: string; options: string[]; onChange: (c: string) => void; label: string; lowData: (c: string) => string | null;
}) {
  const i = Math.max(0, options.indexOf(value));
  const step = (d: number) => onChange(options[(i + d + options.length) % options.length]);
  const warn = lowData(value);
  return (
    <div className="flex h-8 items-center justify-between rounded-md border border-border bg-surface-2" role="group" aria-label={label}>
      <button className={ARROW} aria-label={`${label}: previous`} onClick={() => step(-1)}>‹</button>
      <span className="flex items-center gap-1.5 text-xs font-semibold">
        <CompoundBadge compound={value} size={20} />
        {value}
        {warn && <span className="cursor-help text-warn" title={`Limited data on this tyre, so its estimate is less reliable. ${warn}`}>!</span>}
      </span>
      <button className={ARROW} aria-label={`${label}: next`} onClick={() => step(1)}>›</button>
    </div>
  );
}

/** Stint blocks over a lap axis, with the compound fitted at the start and at each pit stop. */
function StrategyTimeline({ plan, total }: { plan: SimStint[]; total: number }) {
  const span = Math.max(total, sumLaps(plan));
  const starts = [1, ...pitLaps(plan).map((p) => p + 1)];
  const left = (lap: number) => `${(100 * (lap - 1)) / span}%`;
  const ticks = Array.from({ length: Math.floor(span / 10) }, (_, k) => (k + 1) * 10).filter((l) => span - l >= 4);
  return (
    <div className="select-none" aria-hidden>
      <div className="relative h-11 overflow-hidden rounded-t-md bg-bg/60">
        {plan.map((s, i) => {
          const c = COMPOUND[s.compound] ?? "#8a8984";
          return (
            <div key={i} className="absolute inset-y-0 overflow-hidden whitespace-nowrap px-1.5 pt-1.5 text-[11px] font-semibold text-ink-2"
              style={{ left: left(starts[i]), width: `${(100 * s.laps) / span}%`, background: `${c}29`, borderTop: `3px solid ${c}`,
                borderLeft: i ? "2px solid var(--surface-1)" : undefined }}>
              {s.laps / span >= 0.14 ? `${s.compound} · ${s.laps} laps` : s.laps / span >= 0.06 ? s.laps : ""}
            </div>
          );
        })}
      </div>
      <div className="relative h-5 border-t border-border-strong text-[11px] text-ink-3">
        <span className="absolute left-0 top-0.5">Lap 1</span>
        {ticks.map((l) => <span key={l} className="absolute top-0.5 -translate-x-1/2" style={{ left: left(l + 1) }}>{l}</span>)}
        <span className="absolute right-0 top-0.5">{span}</span>
      </div>
      <div className="relative h-6">
        {plan.map((s, i) => (
          <div key={i} className="absolute top-1/2 h-1 -translate-y-1/2"
            style={{ left: left(starts[i]), width: `${(100 * s.laps) / span}%`, background: COMPOUND[s.compound] ?? "#8a8984", opacity: 0.6 }} />
        ))}
        {plan.map((s, i) => (
          <span key={i} className={`absolute top-1/2 -translate-y-1/2 ${i ? "-translate-x-1/2" : ""}`} style={{ left: left(starts[i]) }}>
            <CompoundBadge compound={s.compound} size={20} />
          </span>
        ))}
      </div>
    </div>
  );
}

function PlanEditor({ slot, total, compounds, plan, isActual, onChange, presets, unreliable }: {
  slot: Slot; total: number; compounds: string[]; plan: SimStint[]; isActual: boolean; onChange: (p: SimStint[]) => void;
  presets: { label: string; plan: SimStint[] }[]; unreliable: WhatIfModel["model"]["compounds"];
}) {
  const sum = sumLaps(plan);
  const starts = [1, ...pitLaps(plan).map((p) => p + 1)];
  const end = (i: number) => starts[i] + plan[i].laps; // first lap after stint i
  const set = (i: number, patch: Partial<SimStint>) => onChange(plan.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  // Moving a stint's start lap moves the pit stop: the previous stint gets shorter or longer, the total stays the same.
  const setStart = (i: number, lap: number) => {
    const l = Math.min(end(i) - 1, Math.max(starts[i - 1] + 1, lap));
    onChange(plan.map((s, j) => (j === i - 1 ? { ...s, laps: l - starts[i - 1] } : j === i ? { ...s, laps: end(i) - l } : s)));
  };
  const longest = plan.reduce((best, s, i) => (s.laps > plan[best].laps ? i : best), 0);
  const canSplit = plan[longest].laps >= 10;
  // A new stop splits the longest stint in half and fits a different, well-modelled compound.
  const addStop = () => {
    const s = plan[longest];
    const half = Math.floor(s.laps / 2);
    const next = compounds.find((c) => c !== s.compound && !unreliable[c]?.unreliable) ?? s.compound;
    onChange([...plan.slice(0, longest), { ...s, laps: s.laps - half }, { compound: next, laps: half, start_age: 0 }, ...plan.slice(longest + 1)]);
  };
  const removeStint = (i: number) => {
    if (plan.length < 2) return;
    const merged = plan.filter((_, j) => j !== i);
    const target = Math.max(0, i - 1);
    merged[target] = { ...merged[target], laps: merged[target].laps + plan[i].laps };
    onChange(merged);
  };
  const stops = plan.length - 1;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-bg/40 p-3" style={{ borderTop: `3px solid ${DRIVER[slot.slot]}` }}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-base font-semibold text-ink">{slot.label}</span>
        <span className="text-xs text-ink-2">{stops ? `${stops}-stop strategy` : "No stops"}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] ${isActual ? "border-border text-ink-3" : "border-focus/50 text-focus"}`}>
          {isActual ? "Real strategy" : "Modified"}
        </span>
        <span className="ml-auto flex flex-wrap gap-1.5">
          {presets.map((p) => (
            <button key={p.label} className="btn" onClick={() => onChange(p.plan.map((x) => ({ ...x })))}>{p.label}</button>
          ))}
        </span>
      </div>
      {sum !== total && (
        <p className="text-xs font-medium text-warn">The stints cover {sum} of {total} laps. Use &ldquo;Real strategy&rdquo; to reset.</p>
      )}
      <StrategyTimeline plan={plan} total={total} />
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left">
            <th className="eyebrow w-6 pb-1.5 font-semibold">#</th>
            <th className="eyebrow pb-1.5 font-semibold">Stint</th>
            <th className="eyebrow pb-1.5 font-semibold">Compound</th>
            <th className="eyebrow pb-1.5 font-semibold">Start lap</th>
            <th className="eyebrow pb-1.5 font-semibold" title="Laps already on the set when it is fitted (0 = new set)">Tyre age</th>
            <th className="w-8 pb-1.5"></th>
          </tr>
        </thead>
        <tbody>
          {plan.map((s, i) => (
            <tr key={i} className="border-t border-border/70">
              <td className="py-1.5 font-mono text-ink-3">{i + 1}</td>
              <td className="whitespace-nowrap py-1.5 pr-2">
                <div className="font-medium text-ink">Lap {starts[i]}–{end(i) - 1}</div>
                <div className="text-[11px] text-ink-3">{s.laps} laps</div>
              </td>
              <td className="py-1.5 pr-2">
                <CompoundPicker value={s.compound} options={compounds} label={`${slot.label} stint ${i + 1} compound`}
                  lowData={(c) => unreliable[c]?.unreliable ?? null} onChange={(c) => set(i, { compound: c })} />
              </td>
              <td className="py-1.5 pr-2">
                {i === 0 ? (
                  <div className="flex h-8 items-center justify-center rounded-md border border-dashed border-border text-ink-3" title="Every race starts on lap 1">
                    Lap 1
                  </div>
                ) : (
                  <Stepper value={starts[i]} min={starts[i - 1] + 1} max={end(i) - 1} prefix="Lap"
                    label={`${slot.label} stint ${i + 1} start lap`} onChange={(l) => setStart(i, l)} />
                )}
              </td>
              <td className="py-1.5 pr-2">
                <Stepper value={s.start_age} min={0} max={total} suffix={s.start_age === 0 ? "new" : "used"}
                  label={`${slot.label} stint ${i + 1} tyre age`} onChange={(v) => set(i, { start_age: v })} />
              </td>
              <td className="py-1.5 text-right">
                {plan.length > 1 && (
                  <button className="rounded p-1.5 text-ink-3 hover:bg-surface-3 hover:text-ink" aria-label={`Remove stint ${i + 1}`}
                    title="Remove this stint (its laps go to the neighbouring stint)" onClick={() => removeStint(i)}>
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 8.5h5.6l.7-8.5" />
                    </svg>
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn self-start" onClick={addStop} disabled={!canSplit}
        title={canSplit ? "Split the longest stint in two with a pit stop" : "Every stint is too short to split (needs 10+ laps)"}>
        + Add pit stop
      </button>
    </div>
  );
}

function PositionBars({ pos }: { pos: SimDriver["position"] }) {
  const top = Object.entries(pos.distribution).filter(([, v]) => v >= 0.01).sort((x, y) => y[1] - x[1]).slice(0, 4)
    .sort((x, y) => Number(x[0]) - Number(y[0]));
  return (
    <div className="flex flex-col gap-1">
      {top.map(([p, v]) => (
        <div key={p} className="grid grid-cols-[2.5rem_1fr_3rem] items-center gap-2 text-xs">
          <span className={`font-mono ${Number(p) === pos.actual ? "text-ink" : "text-ink-2"}`}>P{p}</span>
          <span className="h-2.5 overflow-hidden rounded-sm bg-surface-3">
            <span className="block h-full rounded-sm bg-ink-2" style={{ width: `${Math.max(2, v * 100)}%` }} />
          </span>
          <span className="text-right font-mono text-ink-2">{Math.round(v * 100)}%</span>
        </div>
      ))}
      <div className="text-[11px] text-ink-3">Real result: P{pos.actual}</div>
    </div>
  );
}

function DriverResult({ s, r, isActual }: { s: Slot; r: SimDriver; isActual: boolean }) {
  const d = r.delta_vs_actual_strategy;
  // With traffic on, a driver on their real strategy still changes if they now meet the other driver on track.
  const exact = isActual && Math.abs(d.low) < 0.05 && Math.abs(d.high) < 0.05;
  const verdict = exact ? "This is the real strategy, so it reproduces the real race."
    : isActual ? "Real strategy, but they now meet the other driver's new strategy on track."
      : Math.abs(d.median) < 0.05 ? "About the same finish time as the real race"
        : d.median < 0 ? "earlier at the flag than in the real race" : "later at the flag than in the real race";
  const caveats = [...new Set([...r.warnings, ...r.extrapolation, ...(r.offset_dependence.message ? [r.offset_dependence.message] : [])])];
  return (
    <div className="card flex flex-col gap-3 p-4" style={{ borderTop: `3px solid ${DRIVER[s.slot]}` }}>
      <div className="text-sm font-semibold">{s.label}</div>
      <div>
        <div className="eyebrow">Finish time vs the real race</div>
        <div className="text-2xl font-semibold tabular-nums">{fmtDelta(d.median)}</div>
        <div className="text-xs text-ink-2">{verdict}</div>
        {!exact && <div className="mt-0.5 text-[11px] text-ink-3">90% of simulated races: {fmtRange(d)}</div>}
      </div>
      {r.clean_air_delta && r.traffic && !exact && (
        <dl className="grid grid-cols-3 gap-2 rounded-md bg-surface-2 p-2 text-xs">
          <div><dt className="text-[11px] text-ink-3">Held up</dt><dd className="font-mono">~{r.traffic.laps_held_median.toFixed(0)} laps</dd></div>
          <div><dt className="text-[11px] text-ink-3">Passes made</dt><dd className="font-mono">~{r.traffic.passes_median.toFixed(0)}</dd></div>
          <div><dt className="text-[11px] text-ink-3">In clean air</dt><dd className="font-mono">{fmtDelta(r.clean_air_delta.median)}</dd></div>
        </dl>
      )}
      <div>
        <div className="eyebrow mb-1">Likely finishing position</div>
        <PositionBars pos={r.position} />
      </div>
      {caveats.length > 0 && (
        <details className="rounded-md border border-warn/30 bg-warn/[0.05] px-2.5 py-1.5 text-xs">
          <summary className="cursor-pointer text-warn">{caveats.length} caveat{caveats.length > 1 ? "s" : ""} on this estimate</summary>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-ink-2">
            {caveats.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

function SimResults({ result, run, slots, actual }: { result: SimResult; run: Run; slots: Slot[]; actual: (d: number) => SimStint[] }) {
  const gap = result.gap_by_lap;
  const [a, b] = slots;
  const laps = gap ? gap.median.map((_, i) => i + 1) : [];
  const chart: Data[] = gap ? [
    { type: "scatter", mode: "lines", x: [...laps, ...[...laps].reverse()], y: [...gap.high, ...[...gap.low].reverse()],
      fill: "toself", fillcolor: "rgba(195,194,183,0.14)", line: { width: 0 }, hoverinfo: "skip", name: "90% range of the what-if" },
    { type: "scatter", mode: "lines", name: "What-if (median)", x: laps, y: gap.median, line: { color: "#f0efec", width: 2 },
      hovertemplate: `Lap %{x}: ${b.label} %{y:+.1f} s<extra>what-if</extra>` },
    { type: "scatter", mode: "lines", name: "Real race", x: laps, y: gap.actual, line: { color: "#9b9a94", width: 1.5, dash: "dash" },
      hovertemplate: `Lap %{x}: ${b.label} %{y:+.1f} s<extra>real race</extra>` },
  ] : [];
  const neutral: Partial<Shape>[] = [...toRanges(run.scenario.sc), ...toRanges(run.scenario.vsc)].map(([l0, l1]) => ({
    type: "rect", xref: "x", yref: "paper", x0: l0 - 0.5, x1: l1 + 0.5, y0: 0, y1: 1, line: { width: 0 },
    fillcolor: "rgba(250,178,25,0.10)", layer: "below",
  }));
  const pA = result.p_first_ahead;
  const finalGap = gap?.median.at(-1);
  const realGap = gap?.actual.at(-1);
  const behind = (v: number) => `${Math.abs(v).toFixed(1)} s ${v >= 0 ? "behind" : "ahead of"} ${a.label}`;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {slots.map((s) => {
          const r = result.drivers[String(s.driver)];
          return r ? <DriverResult key={s.slot} s={s} r={r} isActual={samePlan(run.plans[s.slot], actual(s.driver))} /> : null;
        })}
        {pA !== undefined && (
          <div className="card flex flex-col gap-3 p-4">
            <div className="text-sm font-semibold">Head to head</div>
            <div>
              <div className="eyebrow">Who finishes ahead</div>
              <div className="mt-1.5 flex h-7 overflow-hidden rounded-md text-xs font-semibold text-bg">
                {pA > 0 && <div className="flex items-center px-2" style={{ width: `${pA * 100}%`, background: DRIVER.a }}>{pA >= 0.15 ? `${a.label} ${Math.round(pA * 100)}%` : ""}</div>}
                {pA < 1 && <div className="flex items-center justify-end px-2" style={{ width: `${(1 - pA) * 100}%`, background: DRIVER.b }}>{1 - pA >= 0.15 ? `${b.label} ${Math.round((1 - pA) * 100)}%` : ""}</div>}
              </div>
              <div className="mt-1 text-[11px] text-ink-3">Share of simulated races in which each driver crosses the line first.</div>
            </div>
            {finalGap !== undefined && realGap !== undefined && (
              <div>
                <div className="eyebrow">Gap at the flag</div>
                <div className="text-sm text-ink">{b.label} {behind(finalGap)}</div>
                <div className="text-[11px] text-ink-3">Real race: {b.label} {behind(realGap)}</div>
              </div>
            )}
          </div>
        )}
      </div>
      {gap && (
        <div className="card p-4">
          <div className="mb-1 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold">Gap between them, lap by lap</h3>
              <p className="text-xs text-ink-3">
                Above zero = {b.label} behind {a.label}. Solid = what-if, dashed = real race, shaded band = 90% range
                {neutral.length ? "; yellow = the safety-car laps you added" : ""}.
              </p>
            </div>
            <Badge tier="E" />
          </div>
          <Plot height={300} data={chart} layout={{ xaxis: { title: { text: "Lap" } }, yaxis: { title: { text: `${b.label} behind ${a.label} (s)` }, zeroline: true },
            shapes: neutral, margin: { l: 64, r: 12, t: 8, b: 64 }, legend: { orientation: "h", y: -0.28 } }} />
        </div>
      )}
      <details className="card px-4 py-2.5 text-xs text-ink-2">
        <summary className="flex cursor-pointer items-center gap-2 font-medium text-ink">
          <Badge tier="A" /> What the simulation assumes ({result.assumptions.length})
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-3">
          {result.assumptions.map((x) => <li key={x}>{x}</li>)}
        </ul>
      </details>
    </div>
  );
}

function Optimiser({ sessionId, slots, scenario, traffic, onLoad }: {
  sessionId: string; slots: Slot[]; scenario: ScenarioIn; traffic: boolean; onLoad: (slot: "a" | "b", p: SimStint[]) => void;
}) {
  const [optSlot, setOptSlot] = useState<"a" | "b">("b");
  const [maxStops, setMaxStops] = useState(2);
  const opt = useMutation({
    mutationFn: () => api.optimise(sessionId, slots.find((s) => s.slot === optSlot)!.driver, maxStops, scenario, traffic),
  });
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!opt.isPending) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [opt.isPending]);
  const elapsed = Math.max(0, Math.round((now - opt.submittedAt) / 1000));
  const resultSlot = slots.find((s) => s.driver === opt.data?.driver)?.slot;

  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-64 flex-1">
          <h3 className="text-sm font-semibold text-ink">Find the best strategy</h3>
          <p className="text-xs text-ink-3">
            Tries every plan with 1 to {maxStops} stop{maxStops > 1 ? "s" : ""} on new tyres (stints of 5+ laps, at least two dry
            compounds), under the race conditions in step 2, and ranks them by finish time.
          </p>
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-ink-2">Driver</span>
          <select value={optSlot} onChange={(e) => setOptSlot(e.target.value as "a" | "b")}>
            {slots.map((s) => <option key={s.slot} value={s.slot}>{s.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-ink-2">Up to</span>
          <select value={maxStops} onChange={(e) => setMaxStops(Number(e.target.value))}>
            {[1, 2, 3].map((n) => <option key={n} value={n}>{n} stop{n > 1 ? "s" : ""}</option>)}
          </select>
        </label>
        <button className="btn" onClick={() => opt.mutate()} disabled={opt.isPending}>
          {opt.isPending && <Spinner size={12} />} Find best strategies
        </button>
      </div>
      {opt.isPending && (
        <p className="text-xs text-ink-3" role="status">
          Searching… {elapsed} s{traffic ? " (the best plans are then re-checked against the real field)" : ""}
        </p>
      )}
      {opt.isError && <Callout tone="warn" title="No strategies could be ranked">{(opt.error as Error).message}</Callout>}
      {opt.data && resultSlot && <OptTable result={opt.data} onLoad={(p) => onLoad(resultSlot, p)} />}
    </div>
  );
}

function OptTable({ result, onLoad }: { result: OptResult; onLoad: (p: SimStint[]) => void }) {
  const traffic = result.mode === "traffic";
  const total = sumLaps(result.actual);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-border">
            <th className="px-2 py-1.5 font-normal">Rank</th>
            <th className="px-2 py-1.5 font-normal">Strategy for {result.code}</th>
            <th className="px-2 py-1.5 font-normal">Finish vs real race{traffic ? " (with traffic)" : ""} <Badge tier="E" /></th>
            <th className="px-2 py-1.5 font-normal">90% range</th>
            {traffic && <th className="px-2 py-1.5 font-normal" title="Same plan with no other cars in the way">Clean air</th>}
            <th className="px-2 py-1.5 font-normal">Caveats</th>
            <th className="px-2 py-1.5 font-normal"></th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-border/60 bg-surface-2/60">
            <td className="px-2 py-2 text-ink-3">Real</td>
            <td className="w-2/5 px-2 py-2"><StintBar plan={result.actual} total={total} /></td>
            <td className="px-2 py-2 font-mono text-ink-3">±0.0 s</td><td></td>{traffic && <td></td>}<td></td><td></td>
          </tr>
          {result.plans.map((p, i) => {
            const main = p.delta_with_traffic ?? p.delta_vs_actual_strategy;
            const caveats = [...p.extrapolation, ...(p.offset_dependence.message ? [p.offset_dependence.message] : [])];
            return (
              <tr key={i} className="border-b border-border/60 hover:bg-surface-2/60">
                <td className="px-2 py-2 font-mono">{i + 1}</td>
                <td className="px-2 py-2">
                  <StintBar plan={p.stints} total={sumLaps(p.stints)} />
                  <div className="mt-0.5 text-[11px] text-ink-3">{stopsText(p.stints)}</div>
                </td>
                <td className="px-2 py-2">
                  <span className={`font-mono text-sm ${main.median < 0 ? "text-ink" : "text-ink-2"}`}>{fmtDelta(main.median)}</span>
                  {p.laps_held ? <div className="text-[11px] text-ink-3">held up ~{p.laps_held.toFixed(0)} laps</div> : null}
                </td>
                <td className="px-2 py-2 font-mono text-ink-3">{fmtRange(main)}</td>
                {traffic && <td className="px-2 py-2 font-mono text-ink-3">{fmtDelta(p.delta_vs_actual_strategy.median)}</td>}
                <td className="px-2 py-2 text-[11px] text-warn" title={caveats.join("\n")}>
                  {p.extrapolation.length > 0 && <div>Tyres older than seen in this race ({p.extrapolation.length})</div>}
                  {p.offset_dependence.flagged && (
                    <div>Gain mostly from compound offsets ({p.offset_dependence.effect_s >= 0 ? "+" : "−"}{Math.abs(p.offset_dependence.effect_s).toFixed(1)} s)</div>
                  )}
                </td>
                <td className="px-2 py-2 text-right"><button className="btn whitespace-nowrap" onClick={() => onLoad(p.stints)}>Edit this plan</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1.5 text-[11px] text-ink-3">
        Negative = faster than the real race. Hover a caveat for details. &ldquo;Compound offsets&rdquo; are the fitted pace
        differences between tyre types, which couldn&apos;t be validated (see the methodology notes).
      </p>
    </div>
  );
}
