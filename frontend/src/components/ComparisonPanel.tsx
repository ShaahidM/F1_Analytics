"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, type CompareMode, type CompareResult, type Lap } from "@/lib/api";
import { COMPOUND } from "@/lib/colors";
import { useStore, type ModeParams } from "@/lib/store";
import { fmtLap } from "@/lib/trace";
import { Badge } from "./Badge";

const MODES: { id: CompareMode; label: string }[] = [
  { id: "fastest", label: "Fastest lap" },
  { id: "same_lap", label: "Same lap number" },
  { id: "same_tyre_age", label: "Same tyre age" },
  { id: "custom", label: "Custom laps" },
];

export function CompoundChip({ compound }: { compound: string | null }) {
  if (!compound) return <span className="text-ink-3">compound n/a</span>;
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: COMPOUND[compound] ?? "#8a8984" }} />
      {compound}
    </span>
  );
}

function LapCard({ slot, lap, code }: { slot: "a" | "b"; lap: Lap; code: string }) {
  return (
    <div className="flex-1 rounded border border-border bg-surface-2 p-2 text-xs" style={{ borderLeft: `3px solid var(--driver-${slot})` }}>
      <div className="flex items-baseline justify-between">
        <span className="font-semibold">
          {slot.toUpperCase()} · {code} · Lap {lap.lap_number}
        </span>
        <span className="font-mono text-sm">{fmtLap(lap.lap_time_s)}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-ink-2">
        <CompoundChip compound={lap.compound} />
        <span>tyre age {lap.tyre_age ?? "n/a"}</span>
        <span>stint {lap.stint ?? "n/a"}</span>
        <span className="font-mono">
          S1 {fmtLap(lap.s1_s)} · S2 {fmtLap(lap.s2_s)} · S3 {fmtLap(lap.s3_s)}
        </span>
        {lap.st_speed !== null && <span>speed trap {lap.st_speed} km/h</span>}
      </div>
    </div>
  );
}

function lapOptions(laps: Lap[], driver: number) {
  return laps.filter((l) => l.driver_number === driver);
}

/** Hint for the input a mode still needs, or null when the selection is complete. */
function missingInput(mode: CompareMode, p: ModeParams): string | null {
  if (mode === "same_lap" && p.lap === undefined) return "Enter a lap number.";
  if (mode === "same_tyre_age" && p.tyre_age === undefined) return "Enter a tyre age (laps completed on the set).";
  if (mode === "custom" && (p.lap_a === undefined || p.lap_b === undefined)) return "Pick a lap for each driver.";
  return null;
}

export function useComparison() {
  const { sessionId, driverA, driverB, mode, params } = useStore();
  return useQuery<CompareResult>({
    queryKey: ["compare", sessionId, driverA, driverB, mode, params],
    queryFn: () => api.compare(sessionId!, { a: driverA!, b: driverB!, mode, ...params }),
    enabled: !!sessionId && driverA !== null && driverB !== null && missingInput(mode, params) === null,
    retry: false,
  });
}

export function ComparisonPanel({ codes }: { codes: Record<number, string> }) {
  const { sessionId, driverA, driverB, mode, params, setMode, setParams } = useStore();
  const laps = useQuery({
    queryKey: ["laps", sessionId, driverA, driverB],
    queryFn: () => api.laps(sessionId!, [driverA!, driverB!]),
    enabled: !!sessionId && driverA !== null && driverB !== null,
  });
  const cmp = useComparison();

  const lapsA = useMemo(() => lapOptions(laps.data ?? [], driverA ?? -1), [laps.data, driverA]);
  const lapsB = useMemo(() => lapOptions(laps.data ?? [], driverB ?? -1), [laps.data, driverB]);
  const compounds = (ls: Lap[]) => [...new Set(ls.map((l) => l.compound).filter(Boolean))] as string[];
  const maxLap = Math.max(0, ...lapsA.map((l) => l.lap_number), ...lapsB.map((l) => l.lap_number));

  if (driverA === null || driverB === null) {
    return <div className="p-4 text-sm text-ink-3">Select two drivers to compare.</div>;
  }

  return (
    <div className="card flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded border border-border">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={`px-3 py-1 text-xs ${mode === m.id ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink-2"}`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {mode === "same_lap" && (
          <label className="text-xs text-ink-2">
            Lap{" "}
            <input type="number" min={1} max={maxLap} className="w-16" value={params.lap ?? ""}
              onChange={(e) => setParams({ lap: e.target.value ? Number(e.target.value) : undefined })} />
          </label>
        )}
        {mode === "same_tyre_age" && (
          <label className="text-xs text-ink-2">
            Tyre age (laps on set){" "}
            <input type="number" min={0} className="w-16" value={params.tyre_age ?? ""}
              onChange={(e) => setParams({ tyre_age: e.target.value ? Number(e.target.value) : undefined })} />
          </label>
        )}
        {(mode === "fastest" || mode === "same_tyre_age") &&
          (["a", "b"] as const).map((slot) => (
            <label key={slot} className="text-xs text-ink-2">
              {slot.toUpperCase()} compound{" "}
              <select value={params[`compound_${slot}`] ?? ""}
                onChange={(e) => setParams({ [`compound_${slot}`]: e.target.value || undefined })}>
                <option value="">any</option>
                {compounds(slot === "a" ? lapsA : lapsB).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
          ))}
        {mode === "custom" &&
          (["a", "b"] as const).map((slot) => (
            <label key={slot} className="text-xs text-ink-2">
              {slot.toUpperCase()} lap{" "}
              <select value={params[`lap_${slot}`] ?? ""}
                onChange={(e) => setParams({ [`lap_${slot}`]: e.target.value ? Number(e.target.value) : undefined })}>
                <option value="">select</option>
                {(slot === "a" ? lapsA : lapsB).map((l) => (
                  <option key={l.lap_number} value={l.lap_number}>
                    L{l.lap_number} · {fmtLap(l.lap_time_s)} · {l.compound ?? "?"} age {l.tyre_age ?? "?"}
                    {l.clean ? "" : " · excluded"}
                  </option>
                ))}
              </select>
            </label>
          ))}
      </div>

      {missingInput(mode, params) && <div className="text-xs text-ink-3">{missingInput(mode, params)}</div>}
      {cmp.isError && <div className="text-xs text-warn">{(cmp.error as Error).message}</div>}
      {cmp.isLoading && <div className="text-xs text-ink-3">Selecting laps…</div>}
      {cmp.data && (
        <>
          <div className="flex gap-2">
            <LapCard slot="a" lap={cmp.data.a} code={codes[driverA] ?? String(driverA)} />
            <LapCard slot="b" lap={cmp.data.b} code={codes[driverB] ?? String(driverB)} />
          </div>
          {cmp.data.equivalent ? (
            <div className="text-xs text-ink-3">
              <Badge tier="C" /> Laps are directly comparable on compound, tyre age, lap and status.
            </div>
          ) : (
            <div className="rounded border border-warn/40 bg-warn/5 px-2 py-1 text-xs text-ink-2">
              <span className="font-semibold text-warn">⚠ Not directly equivalent:</span>{" "}
              {cmp.data.differences.map((d) => d.message).join(" · ")}
            </div>
          )}
        </>
      )}
    </div>
  );
}
