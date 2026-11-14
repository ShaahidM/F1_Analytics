"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

// Queries whose lap flags change once on-track traffic replaces the classification-gap heuristic.
const DEPENDENT = new Set(["laps", "compare", "degradation", "style", "preservation", "modelB", "strategy", "line"]);

/** Starts on-track traffic detection for the session and refreshes dependent views when it completes. */
export function TrafficStatus({ sessionId }: { sessionId: string }) {
  const client = useQueryClient();
  const q = useQuery({
    queryKey: ["traffic", sessionId],
    queryFn: () => api.traffic(sessionId),
    refetchInterval: (query) => (["downloading", "not_started"].includes(query.state.data?.state ?? "not_started") ? 3000 : false),
    staleTime: 0,
  });
  const prev = useRef<string | undefined>(undefined);
  const state = q.data?.state;

  useEffect(() => {
    if (state === "ready" && prev.current && prev.current !== "ready") {
      client.invalidateQueries({ predicate: (query) => DEPENDENT.has(String(query.queryKey[0])) });
    }
    prev.current = state;
  }, [state, client]);

  if (!q.data || state === "unavailable") {
    return <span className="text-ink-3">Traffic: not detectable for this season (no position data)</span>;
  }
  if (state === "ready") return <span className="text-ink-3">Traffic: on-track positions of every car (racing cars, lapped backmarkers, blue flags)</span>;
  if (state === "failed") return <span className="text-warn">Traffic: on-track detection failed; using classification gaps</span>;
  return (
    <span className="text-ink-3">
      Traffic: downloading every car&apos;s position ({q.data.done}/{q.data.total || "…"}), using classification gaps meanwhile
    </span>
  );
}
