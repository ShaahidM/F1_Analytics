"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { AppHeader } from "@/components/AppHeader";
import { ComparisonPanel, useComparison } from "@/components/ComparisonPanel";
import { CornerTable } from "@/components/CornerTable";
import { DegradationView } from "@/components/DegradationView";
import { LapOverlay } from "@/components/LapOverlay";
import { PreservationView } from "@/components/PreservationView";
import { ReplayControls } from "@/components/ReplayControls";
import { SeasonView } from "@/components/SeasonView";
import { SelectionBar } from "@/components/SelectionBar";
import { SessionSummary } from "@/components/SessionSummary";
import { StrategyView } from "@/components/StrategyView";
import { StyleView } from "@/components/StyleView";
import { TelemetryStack } from "@/components/TelemetryStack";
import { TrackMap } from "@/components/TrackMap";
import { Callout, Loading, SectionHeader } from "@/components/ui";
import { Welcome } from "@/components/Welcome";
import { api } from "@/lib/api";
import { useStore, type Tab } from "@/lib/store";

// needs: "longRuns" = races, sprints and practice (qualifying has only 1–3 push laps per set); "race" = races and sprints.
// question: the one-line answer to "what is this tab for?", shown under the tab bar.
const TABS: { id: Tab; label: string; needsTelemetry: boolean; needs: "any" | "longRuns" | "race"; question: string }[] = [
  { id: "compare", label: "Lap comparison", needsTelemetry: true, needs: "any",
    question: "Where on the lap does each driver brake, lift and get back on the throttle, and where is time gained or lost?" },
  { id: "overlay", label: "Lap overlay", needsTelemetry: true, needs: "any",
    question: "How does a driver's behaviour change between laps, e.g. fresh tyres vs worn tyres?" },
  { id: "degradation", label: "Tyre degradation", needsTelemetry: false, needs: "longRuns",
    question: "How fast does each driver lose lap time as their tyres age, once fuel burn is separated out?" },
  { id: "style", label: "Driving style", needsTelemetry: true, needs: "any",
    question: "How do the two drivers differ in throttle use, braking, coasting and corner speed across all clean laps?" },
  { id: "preservation", label: "Pace vs preservation", needsTelemetry: true, needs: "longRuns",
    question: "As tyres age, does a driver look like they're choosing to manage them, or are they losing grip?" },
  { id: "strategy", label: "Strategy", needsTelemetry: false, needs: "race",
    question: "How did stints, pit stops and undercuts shape the gap between them?" },
];

export default function Home() {
  const { view, sessionId, driverA, driverB, tab, setTab } = useStore();
  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => api.session(sessionId!), enabled: !!sessionId && view === "session" });
  const caps = session.data?.capabilities;
  const hasTelemetry = !!caps?.telemetry && !!caps?.position;
  const kind = session.data?.session_type;
  const disabledReason = (t: (typeof TABS)[number]) =>
    t.needsTelemetry && !hasTelemetry ? "Needs telemetry, which is unavailable for this session"
      : t.needs === "longRuns" && kind === "Qualifying" ? "Needs a race or practice long runs: qualifying has only 1–3 push laps per tyre set"
      : t.needs === "race" && kind && kind !== "Race" ? "Needs a race or sprint" : null;
  const current = TABS.find((t) => t.id === tab)!;
  const activeTab: Tab = caps && disabledReason(current) ? (hasTelemetry ? "compare" : "degradation") : tab;
  const active = TABS.find((t) => t.id === activeTab)!;

  const track = useQuery({
    queryKey: ["track", sessionId],
    queryFn: () => api.track(sessionId!),
    enabled: !!sessionId && hasTelemetry && view === "session",
  });
  const cmp = useComparison();
  const [ta, tb] = useQueries({
    queries: (["a", "b"] as const).map((k) => ({
      // Until laps are chosen both keys would be identical (undefined), so give each slot its own placeholder.
      queryKey: ["trace", sessionId, cmp.data?.[k].driver_number ?? `pending-${k}`, cmp.data?.[k].lap_number],
      queryFn: () => api.trace(sessionId!, cmp.data![k].driver_number, cmp.data![k].lap_number),
      enabled: !!cmp.data && hasTelemetry && view === "session",
      retry: false,
    })),
  });

  const codes = Object.fromEntries((session.data?.drivers ?? []).map((d) => [d.driver_number, d.code]));
  const labels = { a: codes[driverA ?? -1] ?? "A", b: codes[driverB ?? -1] ?? "B" };
  const bothDrivers = driverA !== null && driverB !== null;
  const ready = !!sessionId && bothDrivers && !!session.data;
  const slots = bothDrivers
    ? [
        { slot: "a" as const, driver: driverA, label: labels.a },
        { slot: "b" as const, driver: driverB, label: labels.b },
      ]
    : [];

  return (
    <main className="flex min-h-screen flex-col">
      <AppHeader />

      {view === "season" && <SeasonView />}

      {view === "session" && (
        <>
          <SelectionBar />
          {session.data && <SessionSummary session={session.data} labels={bothDrivers ? labels : null} />}
          {!ready && <Welcome hasSession={!!sessionId} />}

          {ready && (
            <>
              <nav aria-label="Analysis" className="flex flex-wrap gap-1 border-b border-border px-5">
                {TABS.map((t) => {
                  const reason = disabledReason(t);
                  const on = activeTab === t.id;
                  return (
                    <button key={t.id} disabled={!!reason} onClick={() => setTab(t.id)} title={reason ?? undefined}
                      aria-current={on ? "page" : undefined}
                      className={`-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35 ${on ? "border-ink text-ink" : "border-transparent text-ink-3 hover:text-ink-2"}`}>
                      {t.label}
                    </button>
                  );
                })}
              </nav>
              <p className="px-5 pt-3 text-xs text-ink-3">{active.question}</p>
            </>
          )}

          {ready && activeTab === "compare" && (
            <>
              <div className="px-5 pt-3"><ComparisonPanel codes={codes} /></div>
              <div className="grid flex-1 grid-cols-1 gap-4 px-5 py-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                <section className="flex flex-col gap-3">
                  {track.isLoading && <Loading text="Building the reference line and corner map" detail="The first load of a session downloads its telemetry." />}
                  {track.isError && <Callout tone="warn">{(track.error as Error).message}</Callout>}
                  {ta.data && tb.data && <ReplayControls a={ta.data} b={tb.data} labels={labels} />}
                  {track.data && <TrackMap track={track.data} a={ta.data} b={tb.data} labels={labels} />}
                </section>
                <section>
                  {(ta.isLoading || tb.isLoading) && <Loading text="Loading lap telemetry" />}
                  {(ta.isError || tb.isError) && <Callout tone="warn">{((ta.error ?? tb.error) as Error).message}</Callout>}
                  {ta.data && tb.data && track.data && <TelemetryStack a={ta.data} b={tb.data} track={track.data} labels={labels} />}
                </section>
              </div>
              {cmp.data && track.data && ta.data && tb.data && (
                <div className="px-5 pb-8">
                  <SectionHeader title="Corner-by-corner" description="Each zone is the same stretch of track for both laps. Click a zone to zoom the map and charts." />
                  <CornerTable sessionId={sessionId} zones={track.data.zones} labels={labels}
                    a={{ driver: cmp.data.a.driver_number, lap: cmp.data.a.lap_number }}
                    b={{ driver: cmp.data.b.driver_number, lap: cmp.data.b.lap_number }} />
                </div>
              )}
            </>
          )}

          {ready && activeTab === "overlay" && (
            <div className="px-5 py-4">
              {track.data ? (
                <LapOverlay key={`${sessionId}-${driverA}-${driverB}`} sessionId={sessionId} slots={slots} track={track.data}
                  initial={cmp.data ? [
                    { slot: "a", driver: cmp.data.a.driver_number, lap: cmp.data.a.lap_number },
                    { slot: "b", driver: cmp.data.b.driver_number, lap: cmp.data.b.lap_number },
                  ] : []} />
              ) : (
                <Loading text="Building the reference line" />
              )}
            </div>
          )}

          {ready && activeTab === "style" && <div className="px-5 py-4"><StyleView sessionId={sessionId} slots={slots} /></div>}
          {ready && activeTab === "preservation" && <div className="px-5 py-4"><PreservationView sessionId={sessionId} slots={slots} /></div>}
          {ready && activeTab === "strategy" && (
            <div className="px-5 py-4"><StrategyView sessionId={sessionId} slots={slots} drivers={session.data?.drivers ?? []} /></div>
          )}
          {ready && activeTab === "degradation" && (
            <div className="px-5 py-4"><DegradationView sessionId={sessionId} slots={slots} practice={kind === "Practice"} /></div>
          )}
        </>
      )}
    </main>
  );
}
