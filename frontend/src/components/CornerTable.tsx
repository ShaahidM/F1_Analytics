"use client";

import { useQueries } from "@tanstack/react-query";
import { api, type MetricDef, type Zone, type ZoneMetrics } from "@/lib/api";
import { DRIVER } from "@/lib/colors";
import { useStore } from "@/lib/store";
import { Badge } from "./Badge";

type Col = { key: string; label: string; digits: number; better?: "higher" | "lower" };

// Ordered as a driver experiences a corner: approach → braking → apex → traction → exit.
const BRAKING_COLS: Col[] = [
  { key: "entry_speed_kmh", label: "Entry speed", digits: 0 },
  { key: "brake_onset_before_apex_m", label: "Brake point (before apex)", digits: 0 },
  { key: "mean_decel_g", label: "Mean decel.", digits: 2 },
  { key: "coast_m", label: "Coasting", digits: 0 },
  { key: "min_speed_kmh", label: "Min speed", digits: 0, better: "higher" },
  { key: "throttle_pickup_m", label: "Throttle pickup", digits: 0 },
  { key: "full_throttle_m", label: "Full throttle", digits: 0 },
  { key: "exit_speed_kmh", label: "Exit speed", digits: 0, better: "higher" },
];
const FLAT_COLS = ["min_speed_kmh", "min_throttle_pct"];

function fmt(v: number | null | undefined, digits: number) {
  if (v === null || v === undefined) return "—";
  const s = v.toFixed(digits);
  return /^-0(\.0+)?$/.test(s) ? s.slice(1) : s; // avoid "-0"
}

function Pair({ a, b, digits, res }: { a?: number | null; b?: number | null; digits: number; res?: [number?, number?] }) {
  return (
    <div className="flex flex-col font-mono leading-tight">
      {([["a", a, res?.[0]], ["b", b, res?.[1]]] as const).map(([k, v, r]) => (
        <span key={k} className="flex items-center gap-1 whitespace-nowrap">
          <span className="inline-block h-1.5 w-1.5 rounded-sm" style={{ background: DRIVER[k] }} />
          {fmt(v, digits)}
          {r !== undefined && r !== null && v !== null && v !== undefined && <span className="text-ink-3">±{r.toFixed(0)}</span>}
        </span>
      ))}
    </div>
  );
}

export function CornerTable({ sessionId, a, b, zones, labels }: {
  sessionId: string; a: { driver: number; lap: number }; b: { driver: number; lap: number }; zones: Zone[];
  labels: { a: string; b: string };
}) {
  const setXRange = useStore((s) => s.setXRange);
  const [qa, qb] = useQueries({
    queries: [a, b].map((x) => ({
      queryKey: ["corners", sessionId, x.driver, x.lap],
      queryFn: () => api.corners(sessionId, x.driver, x.lap),
    })),
  });
  if (qa.isLoading || qb.isLoading) return <div className="p-3 text-xs text-ink-3">Computing corner metrics…</div>;
  if (!qa.data || !qb.data) return <div className="p-3 text-xs text-warn">{((qa.error ?? qb.error) as Error)?.message}</div>;

  const defs: Record<string, MetricDef> = qa.data.definitions;
  const byZone = (rows: ZoneMetrics[]) => Object.fromEntries(rows.map((r) => [r.zone_id, r]));
  const ma = byZone(qa.data.metrics);
  const mb = byZone(qb.data.metrics);

  return (
    <div className="overflow-x-auto rounded border border-border bg-surface-1">
      <table className="w-full text-[11px]">
        <thead className="text-ink-3">
          <tr className="border-b border-border">
            <th className="px-2 py-1 text-left font-normal">Zone</th>
            <th className="px-2 py-1 text-left font-normal">
              Time in zone <Badge tier="C" note={defs.time_in_zone_s?.note} />
            </th>
            {BRAKING_COLS.map((c) => (
              <th key={c.key} className="px-2 py-1 text-left font-normal" title={defs[c.key]?.note}>
                <div>{c.label}</div>
                <div className="flex items-center gap-1 text-[10px]">
                  {defs[c.key]?.unit} <Badge tier={defs[c.key]?.tier ?? "C"} note={defs[c.key]?.note} />
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {zones.map((z) => {
            const ra = ma[z.id] ?? {};
            const rb = mb[z.id] ?? {};
            const ta = ra.time_in_zone_s ?? null;
            const tb = rb.time_in_zone_s ?? null;
            const dt = ta !== null && tb !== null ? tb - ta : null;
            const bpA = ra.brake_onset_before_apex_m;
            const bpB = rb.brake_onset_before_apex_m;
            const resSum = (ra.brake_onset_resolution_m ?? 0) + (rb.brake_onset_resolution_m ?? 0);
            const bpDiff = bpA != null && bpB != null ? bpB - bpA : null;
            return (
              <tr key={z.id} className="border-b border-border/60 align-top hover:bg-surface-2">
                <td className="px-2 py-1">
                  <button onClick={() => setXRange([Math.max(0, z.start_s - 50), z.end_s + 50])}
                    className="font-mono font-semibold text-ink hover:underline" title="Zoom map and charts to this zone">
                    {z.label}
                  </button>
                  <div className="text-[10px] text-ink-3">{z.kind === "flat" ? "flat-out" : `${Math.round(z.apex_s)} m`}</div>
                </td>
                <td className="px-2 py-1">
                  <Pair a={ta} b={tb} digits={3} />
                  {dt !== null && Math.abs(dt) >= 0.005 && (
                    <div className="mt-0.5 flex items-center gap-1 whitespace-nowrap font-mono text-ink-2">
                      <span className="inline-block h-1.5 w-1.5 rounded-sm" style={{ background: dt > 0 ? DRIVER.a : DRIVER.b }} />
                      {dt > 0 ? labels.a : labels.b} −{Math.abs(dt).toFixed(3)}
                    </div>
                  )}
                </td>
                {z.kind === "flat"
                  ? BRAKING_COLS.map((c) => (
                      <td key={c.key} className="px-2 py-1 text-ink-3">
                        {FLAT_COLS.includes(c.key) ? <Pair a={ra[c.key]} b={rb[c.key]} digits={c.digits} /> : c.key === "full_throttle_m" ? (
                          <>min throttle <Pair a={ra.min_throttle_pct} b={rb.min_throttle_pct} digits={0} /></>
                        ) : ""}
                      </td>
                    ))
                  : BRAKING_COLS.map((c) => (
                      <td key={c.key} className="px-2 py-1">
                        <Pair a={ra[c.key]} b={rb[c.key]} digits={c.digits}
                          res={c.key === "brake_onset_before_apex_m" ? [ra.brake_onset_resolution_m ?? undefined, rb.brake_onset_resolution_m ?? undefined] : undefined} />
                        {c.key === "brake_onset_before_apex_m" && bpDiff !== null && (
                          <div className="mt-0.5 whitespace-nowrap text-[10px] text-ink-3">
                            {Math.abs(bpDiff) <= resSum ? "≈ within resolution" : `${bpDiff > 0 ? labels.b : labels.a} ${Math.abs(bpDiff).toFixed(0)} m earlier`}
                          </div>
                        )}
                      </td>
                    ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-2 py-1 text-[10px] text-ink-3">
        Zones are defined once on the session reference lap and shared by both laps, so time-in-zone compares identical
        stretches of track. Distances after the apex (throttle) and before it (brake point) are relative to the reference
        apex. Click a zone to zoom the map and charts.
      </p>
    </div>
  );
}
