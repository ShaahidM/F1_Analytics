"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import type { Track, Trace } from "@/lib/api";
import { DRIVER } from "@/lib/colors";
import { useStore } from "@/lib/store";
import { deltaTime, gridIndex } from "@/lib/trace";
import { Badge } from "./Badge";

type Channel = {
  key: string;
  title: string;
  unit: string;
  tier: "M" | "C";
  note?: string;
  height: number;
  step?: boolean;
  get: (t: Trace) => (number | null)[];
  range?: [number, number];
};

const CHANNELS: Channel[] = [
  { key: "speed", title: "Speed", unit: "km/h", tier: "M", height: 150, get: (t) => t.speed },
  { key: "throttle", title: "Throttle", unit: "%", tier: "M", height: 90, get: (t) => t.throttle, range: [0, 102] },
  { key: "brake", title: "Brake", unit: "on/off", tier: "M", note: "The feed reports brake as binary (0/100), not pressure",
    height: 60, step: true, get: (t) => t.brake.map((v) => (v === null ? null : v > 0 ? 1 : 0)), range: [0, 1.05] },
  { key: "gear", title: "Gear", unit: "", tier: "M", height: 80, step: true, get: (t) => t.gear, range: [0, 8.5] },
  { key: "accel", title: "Longitudinal accel.", unit: "g", tier: "C",
    note: "Local quadratic fit over 7 raw samples (~1.7 s); smoothing underestimates peak braking", height: 90, get: (t) => t.accel_g },
];

const AXIS = {
  stroke: "#8a8984",
  grid: { stroke: "#2b2b28", width: 1 },
  ticks: { stroke: "#33332f", width: 1 },
  font: "10px ui-monospace, monospace",
};

export function useWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

export function Chart({ data, series, height, width, range, step, syncKey, corners }: {
  data: uPlot.AlignedData; series: { label: string; color: string }[]; height: number; width: number;
  range?: [number, number]; step?: boolean; syncKey: string; corners: Track["corners"];
}) {
  const el = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const { setCursorS, setXRange } = useStore.getState();
  const xRange = useStore((s) => s.xRange);
  const cursorS = useStore((s) => s.cursorS);
  const fromPlot = useRef(false);

  useEffect(() => {
    if (!el.current) return;
    const opts: uPlot.Options = {
      width,
      height,
      legend: { show: false },
      cursor: {
        sync: { key: syncKey, setSeries: false },
        drag: { x: true, y: false, setScale: false },
        points: { size: 6 },
      },
      scales: { x: { time: false }, y: range ? { range } : {} },
      axes: [
        { ...AXIS, size: 22, values: (_u, v) => v.map((x) => `${Math.round(x)}`) },
        { ...AXIS, size: 44, space: 18, values: (_u, v) => v.map((x) => `${+x.toFixed(2)}`) },
      ],
      series: [
        {},
        ...series.map((s) => ({
          stroke: s.color,
          width: 1.5,
          label: s.label,
          paths: step ? uPlot.paths.stepped!({ align: 1 }) : undefined,
        })),
      ],
      hooks: {
        setCursor: [
          (u) => {
            const idx = u.cursor.idx;
            if (idx !== null && idx !== undefined && u.cursor.event) {
              fromPlot.current = true;
              setCursorS((u.data[0] as number[])[idx]);
            }
          },
        ],
        setSelect: [
          (u) => {
            if (u.select.width > 4) {
              setXRange([u.posToVal(u.select.left, "x"), u.posToVal(u.select.left + u.select.width, "x")]);
              u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            }
          },
        ],
        draw: [
          (u) => {
            // Corner markers as recessive vertical guides.
            const ctx = u.ctx;
            ctx.save();
            ctx.strokeStyle = "#3a3a36";
            ctx.fillStyle = "#8a8984";
            ctx.font = `${10 * devicePixelRatio}px ui-monospace, monospace`;
            ctx.setLineDash([3 * devicePixelRatio, 3 * devicePixelRatio]);
            for (const c of corners) {
              const x = u.valToPos(c.s, "x", true);
              if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue;
              ctx.beginPath();
              ctx.moveTo(x, u.bbox.top);
              ctx.lineTo(x, u.bbox.top + u.bbox.height);
              ctx.stroke();
              ctx.fillText(`${c.number}${c.letter}`, x + 2 * devicePixelRatio, u.bbox.top + 10 * devicePixelRatio);
            }
            ctx.restore();
          },
        ],
      },
    };
    plot.current = new uPlot(opts, data, el.current);
    return () => {
      plot.current?.destroy();
      plot.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, width, height]);

  useEffect(() => {
    const u = plot.current;
    if (!u) return;
    const xs = u.data[0] as number[];
    const [lo, hi] = xRange ?? [xs[0], xs[xs.length - 1]];
    u.setScale("x", { min: lo, max: hi });
  }, [xRange, data]);

  useEffect(() => {
    const u = plot.current;
    if (!u || cursorS === null) return;
    if (fromPlot.current) {
      fromPlot.current = false;
      return;
    }
    u.setCursor({ left: u.valToPos(cursorS, "x"), top: 10 });
  }, [cursorS]);

  return <div ref={el} />;
}

export function TelemetryStack({ a, b, track, labels }: { a: Trace; b: Trace; track: Track; labels: { a: string; b: string } }) {
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap);
  const cursorS = useStore((s) => s.cursorS);
  const xRange = useStore((s) => s.xRange);
  const setXRange = useStore((s) => s.setXRange);

  const { delta, datasets, deltaData } = useMemo(() => {
    const n = Math.min(a.s.length, b.s.length);
    const xs = a.s.slice(0, n);
    const delta = deltaTime(a, b).slice(0, n);
    return {
      delta,
      datasets: CHANNELS.map((c) => [xs, c.get(a).slice(0, n), c.get(b).slice(0, n)] as uPlot.AlignedData),
      deltaData: [xs, delta] as uPlot.AlignedData,
    };
  }, [a, b]);
  const series = [
    { label: labels.a, color: DRIVER.a },
    { label: labels.b, color: DRIVER.b },
  ];

  const ia = cursorS !== null ? gridIndex(a, cursorS) : null;
  const ib = cursorS !== null ? gridIndex(b, cursorS) : null;
  const readout = (c: Channel, tr: Trace, i: number | null) => {
    if (i === null) return "—";
    const v = c.get(tr)[i];
    if (v === null || v === undefined) return "—";
    if (c.key === "brake") return v > 0 ? "ON" : "off";
    return `${+v.toFixed(c.key === "accel" ? 2 : 0)}`;
  };
  const spacing = ia !== null ? a.sample_spacing_m[ia] : null;

  return (
    <div ref={wrap} className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-[11px] text-ink-3">
        <span>
          x = track distance (m), aligned by projection onto the reference line · drag on a chart to zoom
          {cursorS !== null && <> · cursor {Math.round(cursorS)} m{spacing ? ` · raw sample spacing here ≈ ${spacing} m` : ""}</>}
        </span>
        {xRange && (
          <button onClick={() => setXRange(null)} className="rounded border border-border px-2 py-0.5 text-ink-2 hover:text-ink">
            Reset zoom
          </button>
        )}
      </div>

      <ChartBlock title="Δ time (B − A)" unit="s" tier="C" note="Positive = B behind A at that distance. Distance-aligned, from timing-line-anchored traces"
        readouts={[{ label: `${labels.b} vs ${labels.a}`, color: "#c3c2b7", value: ia !== null && delta[ia] !== null ? `${(delta[ia] as number) >= 0 ? "+" : ""}${(delta[ia] as number).toFixed(3)}` : "—" }]}>
        <Chart data={deltaData} series={[{ label: "Δt", color: "#c3c2b7" }]} height={90} width={width}
          syncKey="telemetry" corners={track.corners} />
      </ChartBlock>

      {CHANNELS.map((c, k) => (
        <ChartBlock key={c.key} title={c.title} unit={c.unit} tier={c.tier} note={c.note}
          readouts={[
            { label: labels.a, color: DRIVER.a, value: readout(c, a, ia) },
            { label: labels.b, color: DRIVER.b, value: readout(c, b, ib) },
          ]}>
          <Chart data={datasets[k]} series={series} height={c.height} width={width} range={c.range} step={c.step}
            syncKey="telemetry" corners={track.corners} />
        </ChartBlock>
      ))}

      <p className="text-[11px] text-ink-3">
        Data quality: A {a.quality.car_samples} car / {a.quality.pos_samples} position samples (max gap {a.quality.max_pos_gap_s}s) ·
        B {b.quality.car_samples} / {b.quality.pos_samples} (max gap {b.quality.max_pos_gap_s}s).
        {(a.quality.has_gaps || b.quality.has_gaps) && <span className="text-warn"> ⚠ telemetry gaps in this lap.</span>}
      </p>
    </div>
  );
}

export function ChartBlock({ title, unit, tier, note, readouts, children }: {
  title: string; unit: string; tier: "M" | "C"; note?: string;
  readouts: { label: string; color: string; value: string }[]; children: React.ReactNode;
}) {
  return (
    <div className="card px-1 pt-1">
      <div className="flex items-center justify-between px-1 text-[11px]">
        <span className="flex items-center gap-2">
          <span className="font-semibold text-ink">{title}</span>
          {unit && <span className="text-ink-3">{unit}</span>}
          <Badge tier={tier} note={note} />
        </span>
        <span className="flex gap-3 font-mono">
          {readouts.map((r) => (
            <span key={r.label} className="flex items-center gap-1 text-ink-2">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: r.color }} />
              {r.label} <span className="text-ink">{r.value}</span>
            </span>
          ))}
        </span>
      </div>
      {children}
    </div>
  );
}
