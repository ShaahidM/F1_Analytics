"use client";

import { useEffect, useRef, useState } from "react";
import type { Trace } from "@/lib/api";
import { useStore } from "@/lib/store";
import { sAtTime, traceDuration } from "@/lib/trace";

const SPEEDS = [0.25, 0.5, 1, 2, 4];
const CURSOR_UPDATE_MS = 66; // charts follow at ~15 Hz; the map redraws every frame

/** Animated replay: both cars advance by elapsed time, so the map shows the real on-track gap. */
export function ReplayControls({ a, b, labels }: { a: Trace; b: Trace; labels: { a: string; b: string } }) {
  const playT = useStore((s) => s.playT);
  const setPlayT = useStore((s) => s.setPlayT);
  const setCursorS = useStore((s) => s.setCursorS);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const duration = Math.max(traceDuration(a), traceDuration(b));
  const raf = useRef<number | null>(null);
  const lastCursor = useRef(0);

  useEffect(() => {
    if (!playing) return;
    let prev = performance.now();
    const tick = (now: number) => {
      const t0 = useStore.getState().playT ?? 0;
      const next = t0 + ((now - prev) / 1000) * speed;
      prev = now;
      if (next >= duration) {
        setPlayT(duration);
        setPlaying(false);
        return;
      }
      setPlayT(next);
      if (now - lastCursor.current > CURSOR_UPDATE_MS) {
        lastCursor.current = now;
        setCursorS(sAtTime(a, next));
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    };
  }, [playing, speed, duration, a, setPlayT, setCursorS]);

  // Leaving the comparison (new laps) resets the replay.
  useEffect(() => () => setPlayT(null), [a, b, setPlayT]);

  const t = playT ?? 0;
  const sA = sAtTime(a, t);
  const sB = sAtTime(b, t);
  const gap = sA - sB;

  return (
    <div className="flex flex-wrap items-center gap-3 card px-3 py-2 text-xs">
      <button
        onClick={() => {
          if (!playing && (playT === null || playT >= duration)) setPlayT(0);
          setPlaying((p) => !p);
        }}
        className="w-16 rounded border border-border bg-surface-2 px-2 py-1 font-semibold text-ink hover:border-ink-3"
      >
        {playing ? "❚❚ Pause" : "▶ Play"}
      </button>
      <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <option key={s} value={s}>{s}×</option>
        ))}
      </select>
      <input
        type="range" min={0} max={duration} step={0.05} value={t} aria-label="Replay time"
        className="h-1 min-w-48 flex-1 accent-[var(--text-secondary)]"
        onChange={(e) => {
          const v = Number(e.target.value);
          setPlayT(v);
          setCursorS(sAtTime(a, v));
        }}
      />
      <span className="w-20 font-mono text-ink">{t.toFixed(2)} s</span>
      <span className="font-mono text-ink-2">
        {playT === null ? "—" : gap >= 0 ? `${labels.a} ahead by ${gap.toFixed(0)} m` : `${labels.b} ahead by ${(-gap).toFixed(0)} m`}
      </span>
      {playT !== null && (
        <button onClick={() => { setPlaying(false); setPlayT(null); }} className="text-ink-3 hover:text-ink-2">
          exit replay
        </button>
      )}
      <span className="basis-full text-[11px] text-ink-3">
        Both laps start together at the timing line; positions are interpolated between ~4 Hz samples. The gap is the
        distance between the two cars at the same elapsed lap time.
      </span>
    </div>
  );
}
