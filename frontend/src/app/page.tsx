"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { ComparisonPanel, useComparison } from "@/components/ComparisonPanel";
import { SelectionBar } from "@/components/SelectionBar";
import { TelemetryStack } from "@/components/TelemetryStack";
import { TrackMap } from "@/components/TrackMap";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";

export default function Home() {
  const { sessionId, driverA, driverB } = useStore();
  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => api.session(sessionId!), enabled: !!sessionId });
  const caps = session.data?.capabilities;
  const hasTelemetry = !!caps?.telemetry && !!caps?.position;

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
      {sessionId && <ComparisonPanel codes={codes} />}

      {sessionId && !hasTelemetry && session.data && (
        <div className="p-6 text-sm text-ink-3">
          Telemetry, track map and racing-line views are unavailable for this session. Lap-time and pit-stop analysis for
          limited-data seasons arrives with the degradation and strategy views (Phases 2–4).
        </div>
      )}

      {hasTelemetry && (
        <div className="grid flex-1 grid-cols-1 gap-4 p-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <section>
            {track.isLoading && <Status text="Building reference line and corner map (first load downloads telemetry)…" />}
            {track.isError && <Status text={(track.error as Error).message} warn />}
            {track.data && <TrackMap track={track.data} a={ta.data} b={tb.data} labels={labels} />}
          </section>
          <section>
            {(ta.isLoading || tb.isLoading) && <Status text="Loading lap telemetry…" />}
            {(ta.isError || tb.isError) && <Status text={((ta.error ?? tb.error) as Error).message} warn />}
            {ta.data && tb.data && track.data && <TelemetryStack a={ta.data} b={tb.data} track={track.data} labels={labels} />}
          </section>
        </div>
      )}
    </main>
  );
}

function Status({ text, warn }: { text: string; warn?: boolean }) {
  return <div className={`rounded border border-border bg-surface-1 p-4 text-sm ${warn ? "text-warn" : "text-ink-3"}`}>{text}</div>;
}
