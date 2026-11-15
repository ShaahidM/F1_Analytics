"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { ComparisonPanel, useComparison } from "@/components/ComparisonPanel";
import { CornerTable } from "@/components/CornerTable";
import { DegradationView } from "@/components/DegradationView";
import { LapOverlay } from "@/components/LapOverlay";
import { PreservationView } from "@/components/PreservationView";
import { ReplayControls } from "@/components/ReplayControls";
import { SelectionBar } from "@/components/SelectionBar";
import { StrategyView } from "@/components/StrategyView";
import { StyleView } from "@/components/StyleView";
import { TelemetryStack } from "@/components/TelemetryStack";
import { TrackMap } from "@/components/TrackMap";
import { TrafficStatus } from "@/components/TrafficStatus";
import { api } from "@/lib/api";
import { useStore, type Tab } from "@/lib/store";

// needs: "longRuns" = races, sprints and practice (qualifying has only 1–3 push laps per set); "race" = races and sprints.
const TABS: { id: Tab; label: string; needsTelemetry: boolean; needs: "any" | "longRuns" | "race" }[] = [
  { id: "compare", label: "Lap comparison", needsTelemetry: true, needs: "any" },
  { id: "overlay", label: "Lap overlay", needsTelemetry: true, needs: "any" },
  { id: "degradation", label: "Tyre degradation", needsTelemetry: false, needs: "longRuns" },
  { id: "style", label: "Driving style", needsTelemetry: true, needs: "any" },
  { id: "preservation", label: "Pace vs preservation", needsTelemetry: true, needs: "longRuns" },
  { id: "strategy", label: "Strategy", needsTelemetry: false, needs: "race" },
];

export default function Home() {
  const { sessionId, driverA, driverB, tab, setTab } = useStore();
  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => api.session(sessionId!), enabled: !!sessionId });
  const caps = session.data?.capabilities;
  const hasTelemetry = !!caps?.telemetry && !!caps?.position;
  const kind = session.data?.session_type;
  const disabledReason = (t: (typeof TABS)[number]) =>
    t.needsTelemetry && !hasTelemetry ? "Needs telemetry, which is unavailable for this session"
      : t.needs === "longRuns" && kind === "Qualifying" ? "Needs a race or practice long runs: qualifying has only 1–3 push laps per tyre set"
      : t.needs === "race" && kind && kind !== "Race" ? "Needs a race or sprint" : null;
  const current = TABS.find((t) => t.id === tab)!;
  const activeTab: Tab = caps && disabledReason(current) ? (hasTelemetry ? "compare" : "degradation") : tab;

  const track = useQuery({
    queryKey: ["track", sessionId],
    queryFn: () => api.track(sessionId!),
    enabled: !!sessionId && hasTelemetry,
  });
  const cmp = useComparison();
  const [ta, tb] = useQueries({
    queries: (["a", "b"] as const).map((k) => ({
      queryKey: ["trace", sessionId, cmp.data?.[k].driver_number, cmp.data?.[k].lap_number],
      queryFn: () => api.trace(sessionId!, cmp.data![k].driver_number, cmp.data![k].lap_number),
      enabled: !!cmp.data && hasTelemetry,
      retry: false,
    })),
  });

  const codes = Object.fromEntries((session.data?.drivers ?? []).map((d) => [d.driver_number, d.code]));
  const labels = { a: codes[driverA ?? -1] ?? "A", b: codes[driverB ?? -1] ?? "B" };
  const bothDrivers = driverA !== null && driverB !== null;
  const slots = bothDrivers
    ? [
        { slot: "a" as const, driver: driverA, label: labels.a },
        { slot: "b" as const, driver: driverB, label: labels.b },
      ]
    : [];

  return (
    <main className="flex min-h-screen flex-col">
      <SelectionBar />
      {caps && caps.notes.length > 0 && (
        <div className="border-b border-border bg-warn/5 px-4 py-2 text-xs text-ink-2">
          {caps.notes.map((n) => (
            <p key={n}>ⓘ {n}</p>
          ))}
        </div>
      )}

      {sessionId && bothDrivers && (
        <nav className="flex gap-1 border-b border-border bg-surface-1 px-4 pt-2">
          {TABS.map((t) => {
            const reason = disabledReason(t);
            return (
              <button key={t.id} disabled={!!reason} onClick={() => setTab(t.id)} title={reason ?? undefined}
                className={`rounded-t border border-b-0 px-3 py-1.5 text-xs ${activeTab === t.id ? "border-border bg-bg text-ink" : "border-transparent text-ink-3 hover:text-ink-2"} disabled:opacity-40`}>
                {t.label}
              </button>
            );
          })}
          <span className="ml-auto self-center pb-1 text-[10px]"><TrafficStatus sessionId={sessionId} /></span>
        </nav>
      )}

      {sessionId && !bothDrivers && <div className="p-4 text-sm text-ink-3">Select two drivers to compare.</div>}

      {sessionId && bothDrivers && activeTab === "compare" && (
        <>
          <ComparisonPanel codes={codes} />
          <div className="grid flex-1 grid-cols-1 gap-4 p-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <section className="flex flex-col gap-3">
              {track.isLoading && <Status text="Building reference line and corner map (first load downloads telemetry)…" />}
              {track.isError && <Status text={(track.error as Error).message} warn />}
              {ta.data && tb.data && <ReplayControls a={ta.data} b={tb.data} labels={labels} />}
              {track.data && <TrackMap track={track.data} a={ta.data} b={tb.data} labels={labels} />}
            </section>
            <section>
              {(ta.isLoading || tb.isLoading) && <Status text="Loading lap telemetry…" />}
              {(ta.isError || tb.isError) && <Status text={((ta.error ?? tb.error) as Error).message} warn />}
              {ta.data && tb.data && track.data && <TelemetryStack a={ta.data} b={tb.data} track={track.data} labels={labels} />}
            </section>
          </div>
          {cmp.data && track.data && ta.data && tb.data && (
            <div className="px-4 pb-6">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-3">Corner-by-corner</h2>
              <CornerTable sessionId={sessionId} zones={track.data.zones} labels={labels}
                a={{ driver: cmp.data.a.driver_number, lap: cmp.data.a.lap_number }}
                b={{ driver: cmp.data.b.driver_number, lap: cmp.data.b.lap_number }} />
            </div>
          )}
        </>
      )}

      {sessionId && bothDrivers && activeTab === "overlay" && (
        <div className="p-4">
          {track.data ? (
            <LapOverlay key={`${sessionId}-${driverA}-${driverB}`} sessionId={sessionId} slots={slots} track={track.data}
              initial={cmp.data ? [
                { slot: "a", driver: cmp.data.a.driver_number, lap: cmp.data.a.lap_number },
                { slot: "b", driver: cmp.data.b.driver_number, lap: cmp.data.b.lap_number },
              ] : []} />
          ) : (
            <Status text="Building reference line…" />
          )}
        </div>
      )}

      {sessionId && bothDrivers && activeTab === "style" && (
        <div className="p-4">
          <StyleView sessionId={sessionId} slots={slots} />
        </div>
      )}

      {sessionId && bothDrivers && activeTab === "preservation" && (
        <div className="p-4">
          <PreservationView sessionId={sessionId} slots={slots} />
        </div>
      )}

      {sessionId && bothDrivers && activeTab === "strategy" && (
        <div className="p-4">
          <StrategyView sessionId={sessionId} slots={slots} drivers={session.data?.drivers ?? []} />
        </div>
      )}

      {sessionId && bothDrivers && activeTab === "degradation" && (
        <div className="p-4">
          <DegradationView sessionId={sessionId} slots={slots} practice={kind === "Practice"} />
        </div>
      )}
    </main>
  );
}

function Status({ text, warn }: { text: string; warn?: boolean }) {
  return <div className={`rounded border border-border bg-surface-1 p-4 text-sm ${warn ? "text-warn" : "text-ink-3"}`}>{text}</div>;
}
