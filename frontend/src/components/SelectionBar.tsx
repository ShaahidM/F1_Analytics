"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wider text-ink-3">{label}</span>
      {children}
    </label>
  );
}

export function SelectionBar() {
  const { year, sessionId, driverA, driverB, setYear, setSession, setDrivers } = useStore();

  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons });
  const events = useQuery({ queryKey: ["events", year], queryFn: () => api.events(year!), enabled: year !== null });
  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => api.session(sessionId!), enabled: !!sessionId });

  useEffect(() => {
    if (year === null && seasons.data?.length) setYear(seasons.data[0].year);
  }, [seasons.data, year, setYear]);

  const event = events.data?.find((e) => e.sessions.some((s) => s.id === sessionId));
  const drivers = session.data?.drivers ?? [];

  return (
    <div className="flex flex-wrap items-end gap-4 border-b border-border bg-surface-1 px-4 py-3">
      <div className="mr-4">
        <div className="text-sm font-semibold tracking-wide">F1 Telemetry Lab</div>
        <div className="text-[10px] text-ink-3">two-driver performance &amp; tyre analysis</div>
      </div>

      <Field label="Season">
        <select value={year ?? ""} onChange={(e) => setYear(Number(e.target.value))}>
          {seasons.data?.map((s) => (
            <option key={s.year} value={s.year}>
              {s.year} {s.source === "openf1" ? "" : "· limited data"}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Grand Prix">
        <select
          className="w-64"
          value={event ? String(event.meeting_key) : ""}
          disabled={!events.data}
          onChange={(e) => {
            const ev = events.data?.find((x) => String(x.meeting_key) === e.target.value);
            const race = ev?.sessions.find((s) => s.session_name === "Race" && s.available) ?? ev?.sessions.find((s) => s.available);
            setSession(race?.id ?? null);
          }}
        >
          <option value="">{events.isLoading ? "Loading…" : "Select a Grand Prix"}</option>
          {events.data?.map((e) => {
            const any = e.sessions.some((s) => s.available);
            return (
              <option key={e.meeting_key} value={String(e.meeting_key)} disabled={!any}>
                R{e.round} · {e.meeting_name}
                {any ? "" : " (not yet run)"}
              </option>
            );
          })}
        </select>
      </Field>

      <Field label="Session">
        <select value={sessionId ?? ""} disabled={!event} onChange={(e) => setSession(e.target.value)}>
          {event?.sessions.map((s) => (
            <option key={s.id} value={s.id} disabled={!s.available}>
              {s.session_name}
            </option>
          ))}
        </select>
      </Field>

      {(["a", "b"] as const).map((slot) => {
        const value = slot === "a" ? driverA : driverB;
        const other = slot === "a" ? driverB : driverA;
        return (
          <Field key={slot} label={`Driver ${slot.toUpperCase()}`}>
            <div className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-sm" style={{ background: `var(--driver-${slot})` }} />
              <select
                className="w-52"
                value={value ?? ""}
                disabled={!drivers.length}
                onChange={(e) => {
                  const v = e.target.value ? Number(e.target.value) : null;
                  if (slot === "a") setDrivers(v, driverB);
                  else setDrivers(driverA, v);
                }}
              >
                <option value="">{session.isLoading ? "Loading…" : "Select driver"}</option>
                {drivers.map((d) => (
                  <option key={d.driver_number} value={d.driver_number} disabled={d.driver_number === other}>
                    {d.code} · {d.full_name} ({d.team})
                  </option>
                ))}
              </select>
            </div>
          </Field>
        );
      })}
    </div>
  );
}
