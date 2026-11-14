"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import type uPlot from "uplot";
import { api, type Lap, type Trace, type Track } from "@/lib/api";
import { LAP_RAMP } from "@/lib/colors";
import { elapsed, fmtLap } from "@/lib/trace";
import { Badge } from "./Badge";
import { Chart, ChartBlock, useWidth } from "./TelemetryStack";

const MAX_PER_DRIVER = 4;

type Pick = { slot: "a" | "b"; driver: number; lap: number };
type Slot = { slot: "a" | "b"; driver: number; label: string };

/** Overlay several laps from either driver to see how behaviour changes through a stint or session. */
export function LapOverlay({ sessionId, slots, track, initial }: {
  sessionId: string; slots: Slot[]; track: Track; initial: Pick[];
}) {
  const [picks, setPicks] = useState<Pick[]>(initial);
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap);

  const laps = useQuery({
    queryKey: ["laps", sessionId, slots[0].driver, slots[1].driver],
    queryFn: () => api.laps(sessionId, slots.map((s) => s.driver)),
  });
  const lapInfo = (p: Pick): Lap | undefined => laps.data?.find((l) => l.driver_number === p.driver && l.lap_number === p.lap);

  // Colour: per-driver ordinal ramp by tyre age (darker = fresher tyres), so tyre-life order reads from colour.
  const colored = useMemo(() => {
    const out: (Pick & { color: string; name: string })[] = [];
    for (const s of slots) {
      const mine = picks.filter((p) => p.slot === s.slot)
        .sort((x, y) => ((lapInfo(x)?.tyre_age ?? 0) - (lapInfo(y)?.tyre_age ?? 0)) || x.lap - y.lap);
      mine.forEach((p, i) => out.push({ ...p, color: LAP_RAMP[s.slot][i], name: `${s.label} L${p.lap}` }));
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picks, laps.data, slots]);

  const traces = useQueries({
    queries: colored.map((p) => ({
      queryKey: ["trace", sessionId, p.driver, p.lap],
      queryFn: () => api.trace(sessionId, p.driver, p.lap),
      retry: false,
    })),
  });
  const corners = useQueries({
    queries: colored.map((p) => ({
      queryKey: ["corners", sessionId, p.driver, p.lap],
      queryFn: () => api.corners(sessionId, p.driver, p.lap),
      retry: false,
    })),
  });

  const ready = traces.length > 0 && traces.every((t) => t.data);
  const traceKey = traces.map((t) => t.dataUpdatedAt).join();
  const data = useMemo(() => {
    if (!ready) return null;
    const ts = traces.map((t) => t.data as Trace);
    const n = Math.min(...ts.map((t) => t.s.length));
    const xs = ts[0].s.slice(0, n);
    const base = elapsed(ts[0]);
    const mk = (get: (t: Trace) => (number | null)[]) => [xs, ...ts.map((t) => get(t).slice(0, n))] as uPlot.AlignedData;
    return {
      speed: mk((t) => t.speed),
      throttle: mk((t) => t.throttle),
      brake: mk((t) => t.brake.map((v) => (v === null ? null : v > 0 ? 1 : 0))),
      delta: mk((t) => elapsed(t).map((v, i) => (v === null || base[i] === null ? null : v - (base[i] as number)))),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, traceKey]);

  const series = colored.map((p) => ({ label: p.name, color: p.color }));
  const add = (slot: "a" | "b", lap: number) => {
    const s = slots.find((x) => x.slot === slot)!;
    if (picks.some((p) => p.slot === slot && p.lap === lap)) return;
    if (picks.filter((p) => p.slot === slot).length >= MAX_PER_DRIVER) return;
    setPicks([...picks, { slot, driver: s.driver, lap }]);
  };

  return (
    <div ref={wrap} className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-4 rounded border border-border bg-surface-1 px-3 py-2 text-xs">
        {slots.map((s) => (
          <div key={s.slot} className="flex flex-wrap items-center gap-2">
            <span className="font-semibold" style={{ color: `var(--driver-${s.slot})` }}>{s.label}</span>
            {colored.filter((p) => p.slot === s.slot).map((p) => {
              const l = lapInfo(p);
              return (
                <span key={p.lap} className="flex items-center gap-1 rounded border border-border bg-surface-2 px-2 py-0.5 font-mono">
                  <span className="inline-block h-2 w-3 rounded-sm" style={{ background: p.color }} />
                  L{p.lap} · {fmtLap(l?.lap_time_s)} · {l?.compound ?? "?"} age {l?.tyre_age ?? "?"}
                  <button className="ml-1 text-ink-3 hover:text-ink" aria-label={`Remove lap ${p.lap}`}
                    onClick={() => setPicks(picks.filter((x) => !(x.slot === p.slot && x.lap === p.lap)))}>×</button>
                </span>
              );
            })}
            <select value="" onChange={(e) => e.target.value && add(s.slot, Number(e.target.value))}
              disabled={picks.filter((p) => p.slot === s.slot).length >= MAX_PER_DRIVER}>
              <option value="">+ add lap</option>
              {laps.data?.filter((l) => l.driver_number === s.driver && l.lap_start).map((l) => (
                <option key={l.lap_number} value={l.lap_number}>
                  L{l.lap_number} · {fmtLap(l.lap_time_s)} · {l.compound ?? "?"} age {l.tyre_age ?? "?"}{l.clean ? "" : " · excluded"}
                </option>
              ))}
            </select>
          </div>
        ))}
        <span className="basis-full text-[10px] text-ink-3">
          Up to {MAX_PER_DRIVER} laps per driver. Within a driver, darker = fresher tyres, lighter = older. Δ time is relative
          to the first lap listed ({colored[0]?.name ?? "—"}).
        </span>
      </div>

      {traces.some((t) => t.isLoading) && <div className="text-xs text-ink-3">Loading lap telemetry…</div>}
      {traces.some((t) => t.isError) && <div className="text-xs text-warn">Some laps have no usable telemetry and were skipped.</div>}

      {data && (
        <>
          <ChartBlock title={`Δ time vs ${colored[0].name}`} unit="s" tier="C" readouts={[]}>
            <Chart data={data.delta} series={series} height={110} width={width} syncKey="overlay" corners={track.corners} />
          </ChartBlock>
          <ChartBlock title="Speed" unit="km/h" tier="M" readouts={[]}>
            <Chart data={data.speed} series={series} height={170} width={width} syncKey="overlay" corners={track.corners} />
          </ChartBlock>
          <ChartBlock title="Throttle" unit="%" tier="M" readouts={[]}>
            <Chart data={data.throttle} series={series} height={100} width={width} range={[0, 102]} syncKey="overlay" corners={track.corners} />
          </ChartBlock>
          <ChartBlock title="Brake" unit="on/off" tier="M" readouts={[]}>
            <Chart data={data.brake} series={series} height={70} width={width} range={[0, 1.05]} step syncKey="overlay" corners={track.corners} />
          </ChartBlock>
          <div className="flex flex-wrap gap-3 text-[11px] text-ink-2">
            {series.map((s) => (
              <span key={s.label} className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm" style={{ background: s.color }} />{s.label}</span>
            ))}
          </div>
        </>
      )}

      {corners.every((c) => c.data) && corners.length > 0 && (
        <BrakePointTable track={track} colored={colored} results={corners.map((c) => c.data!)} />
      )}
    </div>
  );
}

function BrakePointTable({ track, colored, results }: {
  track: Track; colored: { color: string; name: string }[];
  results: { metrics: { zone_id: number; [k: string]: number | null | undefined }[] }[];
}) {
  const braking = track.zones.filter((z) => z.kind === "braking");
  return (
    <section className="overflow-x-auto rounded border border-border bg-surface-1">
      <h3 className="flex items-center gap-2 px-2 pt-2 text-xs font-semibold">
        Brake point, minimum speed and zone time per lap <Badge tier="C" note="Brake point = metres before the reference apex, ± half the raw sample spacing" />
      </h3>
      <table className="w-full text-[11px]">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-border">
            <th className="px-2 py-1 font-normal">Zone</th>
            {colored.map((c) => (
              <th key={c.name} className="px-2 py-1 font-normal">
                <span className="mr-1 inline-block h-2 w-3 rounded-sm" style={{ background: c.color }} />{c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {braking.map((z) => (
            <tr key={z.id} className="border-b border-border/60">
              <td className="px-2 py-1 font-mono font-semibold">{z.label}</td>
              {results.map((r, i) => {
                const m = r.metrics.find((x) => x.zone_id === z.id);
                return (
                  <td key={i} className="px-2 py-1 font-mono">
                    <div>brake {m?.brake_onset_before_apex_m?.toFixed(0) ?? "—"}<span className="text-ink-3"> ±{m?.brake_onset_resolution_m?.toFixed(0) ?? "?"} m</span></div>
                    <div className="text-ink-2">min {m?.min_speed_kmh?.toFixed(0) ?? "—"} km/h · {m?.time_in_zone_s?.toFixed(3) ?? "—"} s</div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
