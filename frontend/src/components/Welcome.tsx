"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import { Spinner } from "./ui";

const FEATURES = [
  ["Lap comparison", "Speed, throttle and braking on the same distance axis, an animated replay and a corner-by-corner table."],
  ["Tyre degradation", "Lap-time trends per stint, with fuel burn separated by a race-wide model."],
  ["Pace vs preservation", "Where each driver lifts, brakes earlier or feeds the throttle in as tyres age, and what else could explain it."],
  ["Season comparison", "The same two drivers race by race across a whole season."],
];

/** First-run screen: what the tool does, how to start, and a one-click example (looked up from the API). */
export function Welcome({ hasSession }: { hasSession: boolean }) {
  const openSession = useStore((s) => s.openSession);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExample = async () => {
    setLoading(true);
    setError(null);
    try {
      const events = await api.events(2024);
      const race = events.find((e) => e.meeting_name.includes("Italian"))?.sessions.find((s) => s.session_name === "Race");
      if (!race) throw new Error("Example race not found");
      const detail = await api.session(race.id);
      const num = (code: string) => detail.drivers.find((d) => d.code === code)?.driver_number;
      const a = num("LEC");
      const b = num("PIA");
      if (a === undefined || b === undefined) throw new Error("Example drivers not found");
      openSession(2024, race.id, a, b);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-5 py-10">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Compare two drivers, lap by lap and corner by corner</h1>
        <p className="mt-1 text-sm text-ink-2">
          {hasSession
            ? "Now pick two drivers in the bar above."
            : "Pick a season, Grand Prix, session and two drivers in the bar above, or start with an example."}
        </p>
      </div>
      {!hasSession && (
        <div>
          <button className="btn btn-primary" onClick={loadExample} disabled={loading}>
            {loading && <Spinner size={12} />} Load example: 2024 Italian GP, Leclerc vs Piastri
          </button>
          {error && <p className="mt-2 text-xs text-warn">{error}</p>}
          <p className="mt-2 text-xs text-ink-3">The first load of a session downloads its telemetry (about 15–30 s); after that it&apos;s cached.</p>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {FEATURES.map(([title, text]) => (
          <div key={title} className="card p-4">
            <div className="text-sm font-medium text-ink">{title}</div>
            <p className="mt-1 text-xs leading-relaxed text-ink-3">{text}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-ink-3">
        Every number is labelled as measured, calculated, estimated, an interpretation or an assumption. See &ldquo;About the
        data&rdquo; for what public F1 data can and can&apos;t tell you.
      </p>
    </div>
  );
}
