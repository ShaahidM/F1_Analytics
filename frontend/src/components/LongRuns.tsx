"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type StintTrend } from "@/lib/api";
import { DRIVER } from "@/lib/colors";
import { fmtLap } from "@/lib/trace";
import { Badge } from "./Badge";
import { CompoundChip } from "./ComparisonPanel";

type Slot = { slot: "a" | "b"; driver: number; label: string };
const COMPOUND_ORDER = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"];

/** Every driver's detected long runs in a practice session, grouped by compound and ordered by median pace. */
export function LongRuns({ sessionId, slots, includeFlagged }: { sessionId: string; slots: Slot[]; includeFlagged: boolean }) {
  const q = useQuery({
    queryKey: ["longruns", sessionId, includeFlagged],
    queryFn: () => api.longRuns(sessionId, includeFlagged),
  });
  if (q.isLoading) return <div className="text-xs text-ink-3">Finding long runs across the field…</div>;
  if (q.isError) return <div className="text-xs text-warn">{(q.error as Error).message}</div>;
  const runs = q.data?.runs ?? [];
  if (!runs.length) return <div className="text-xs text-ink-3">No long runs (5+ consistent laps on one tyre set) were found in this session.</div>;

  const rank = (c: string | null) => (c && COMPOUND_ORDER.includes(c) ? COMPOUND_ORDER.indexOf(c) : COMPOUND_ORDER.length);
  const sorted = [...runs].sort((x, y) => rank(x.compound) - rank(y.compound) || (x.median_lap_s ?? 0) - (y.median_lap_s ?? 0));
  const best: Record<string, number> = {};
  for (const r of sorted) {
    const k = r.compound ?? "?";
    if (r.median_lap_s !== null && best[k] === undefined) best[k] = r.median_lap_s;
  }
  const slotOf = (d: number) => slots.find((s) => s.driver === d);
  const trend = (r: StintTrend) => {
    const f = r.raw_trend;
    if (!f) return "—";
    const flat = f.ci_low <= 0 && f.ci_high >= 0;
    return `${f.slope >= 0 ? "+" : ""}${f.slope.toFixed(3)} [${f.ci_low.toFixed(3)}, ${f.ci_high.toFixed(3)}]${flat ? " ≈0" : ""}`;
  };

  return (
    <section className="overflow-x-auto card">
      <h3 className="flex flex-wrap items-center gap-2 px-2 pt-2 text-xs font-semibold">
        Long runs, whole field <Badge tier="C" note="Runs of 5+ laps within ±2.5% of the run's median pace on one tyre set, with at least 3 consecutive laps" />
      </h3>
      <p className="px-2 text-[11px] text-ink-3">
        Ordered by median lap time within each compound. Fuel loads and engine modes are unknown and differ between teams, so
        this order is not a race-pace ranking; the trend (s per lap) is the more comparable number.
      </p>
      <table className="mt-1 w-full text-xs">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-border">
            <th className="px-2 py-1 font-normal">Driver</th>
            <th className="px-2 py-1 font-normal">Team</th>
            <th className="px-2 py-1 font-normal">Compound</th>
            <th className="px-2 py-1 font-normal">Tyre age at start</th>
            <th className="px-2 py-1 font-normal">Laps</th>
            <th className="px-2 py-1 font-normal">Median lap <Badge tier="M" /></th>
            <th className="px-2 py-1 font-normal">Gap to quickest run on compound</th>
            <th className="px-2 py-1 font-normal">Pace trend, s/lap <Badge tier="E" note={`Theil–Sen slope with ${(q.data?.ci_level ?? 0.9) * 100}% CI; includes fuel burn and track evolution`} /></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const s = slotOf(r.driver_number);
            const gap = r.median_lap_s !== null ? r.median_lap_s - best[r.compound ?? "?"] : null;
            return (
              <tr key={`${r.driver_number}-${r.stint}`} className={`border-b border-border/60 ${s ? "bg-surface-2 text-ink" : "text-ink-2"}`}>
                <td className="px-2 py-1 font-mono font-semibold">
                  {s && <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: DRIVER[s.slot] }} />}
                  {r.code ?? r.driver_number}
                </td>
                <td className="px-2 py-1">{r.team ?? "—"}</td>
                <td className="px-2 py-1"><CompoundChip compound={r.compound} /></td>
                <td className="px-2 py-1 font-mono">{r.tyre_age_start ?? "?"} laps</td>
                <td className="px-2 py-1 font-mono">{r.n_used}</td>
                <td className="px-2 py-1 font-mono">{fmtLap(r.median_lap_s)}</td>
                <td className="px-2 py-1 font-mono">{gap === null ? "—" : gap < 0.0005 ? "quickest" : `+${gap.toFixed(3)}`}</td>
                <td className="px-2 py-1 font-mono">{trend(r)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
