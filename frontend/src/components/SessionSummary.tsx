"use client";

import type { SessionDetail } from "@/lib/api";
import { TrafficStatus } from "./TrafficStatus";
import { Callout, Chip } from "./ui";

/** Title strip for the selected session: what it is, what data it has, and any caveats. */
export function SessionSummary({ session, labels }: { session: SessionDetail; labels: { a: string; b: string } | null }) {
  const c = session.capabilities;
  const date = session.date_start ? new Date(session.date_start).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
  return (
    <div className="flex flex-col gap-2 border-b border-border px-5 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-lg font-semibold tracking-tight">{session.meeting_name}</h1>
        <span className="text-sm text-ink-2">{session.session_name}</span>
        <span className="text-xs text-ink-3">{session.circuit_name} · {date}{session.round ? ` · Round ${session.round}` : ""}</span>
        {labels && (
          <span className="ml-auto flex items-center gap-2 text-sm font-medium">
            <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-driver-a" />{labels.a}</span>
            <span className="text-ink-3">vs</span>
            <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-driver-b" />{labels.b}</span>
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip ok={c.telemetry}>Telemetry</Chip>
        <Chip ok={c.position}>Track position</Chip>
        <Chip ok={c.sectors}>Sector times</Chip>
        <Chip ok={c.compounds}>Tyre compounds</Chip>
        <Chip ok={c.pit}>Pit stops</Chip>
        <Chip ok={c.race_control}>Race control</Chip>
        <span className="ml-auto text-[11px]">{labels && <TrafficStatus sessionId={session.id} />}</span>
      </div>
      {c.notes.map((n) => <Callout key={n} tone="warn">{n}</Callout>)}
    </div>
  );
}
