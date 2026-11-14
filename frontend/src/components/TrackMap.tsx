"use client";

import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Corner, Track, Trace } from "@/lib/api";
import { DRIVER, INPUTS, SPEED_RAMP, speedColor } from "@/lib/colors";
import { useStore, type ColorBy } from "@/lib/store";
import { deltaTime, gridIndex } from "@/lib/trace";
import { Badge } from "./Badge";

const OFFSET_PX = 3.5; // visual separation between the two traces (data has no lateral information)
const PAD = 28;
const CORNER_WINDOW_M = 250;
const FASTER_SEGMENT = 10; // grid points (= 50 m on a 5 m grid)
const FASTER_EPS_S = 0.01; // below this per-segment gain the result is within timing noise

type Pt = [number, number];

const COLOR_MODES: { id: ColorBy; label: string }[] = [
  { id: "driver", label: "Driver" },
  { id: "speed", label: "Speed" },
  { id: "inputs", label: "Brake / throttle" },
  { id: "faster", label: "Faster driver" },
];

function rotate(x: number, y: number, deg: number): Pt {
  const r = (deg * Math.PI) / 180;
  return [x * Math.cos(r) - y * Math.sin(r), x * Math.sin(r) + y * Math.cos(r)];
}

export function TrackMap({ track, a, b, labels }: { track: Track; a?: Trace; b?: Trace; labels: { a: string; b: string } }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const transformRef = useRef<ZoomTransform>(zoomIdentity);
  const zoomRef = useRef<ZoomBehavior<HTMLCanvasElement, unknown> | null>(null);
  const [size, setSize] = useState({ w: 600, h: 520 });
  const { cursorS, setCursorS, colorBy, setColorBy, setXRange } = useStore();

  const rot = track.rotation ?? 0;
  const refPts = useMemo(() => track.reference.x.map((x, i) => rotate(x, track.reference.y[i], rot)), [track, rot]);

  // Base fit: data → screen without zoom (y flipped: data y is up).
  const base = useMemo(() => {
    const xs = refPts.map((p) => p[0]);
    const ys = refPts.map((p) => p[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const k = Math.min((size.w - 2 * PAD) / (x1 - x0), (size.h - 2 * PAD) / (y1 - y0));
    const ox = (size.w - k * (x1 - x0)) / 2;
    const oy = (size.h - k * (y1 - y0)) / 2;
    return (p: Pt): Pt => [ox + (p[0] - x0) * k, size.h - (oy + (p[1] - y0) * k)];
  }, [refPts, size]);

  const toScreen = useCallback((p: Pt): Pt => transformRef.current.apply(base(p)), [base]);

  const tracePts = useCallback(
    (tr: Trace): (Pt | null)[] =>
      tr.x.map((x, i) => (x === null || tr.y[i] === null ? null : rotate(x, tr.y[i] as number, rot))),
    [rot],
  );
  const ptsA = useMemo(() => (a ? tracePts(a) : []), [a, tracePts]);
  const ptsB = useMemo(() => (b ? tracePts(b) : []), [b, tracePts]);
  const delta = useMemo(() => (a && b ? deltaTime(a, b) : null), [a, b]);
  const speedRange = useMemo(() => {
    const v = [...(a?.speed ?? []), ...(b?.speed ?? [])].filter((x): x is number => x !== null);
    return v.length ? [Math.min(...v), Math.max(...v)] : [0, 350];
  }, [a, b]);

  const draw = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    // Track band from the reference line.
    const scr = refPts.map(toScreen);
    ctx.strokeStyle = "#2b2b28";
    ctx.lineWidth = 14;
    ctx.beginPath();
    scr.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
    ctx.closePath();
    ctx.stroke();

    const offsetPath = (pts: (Pt | null)[], sign: number): (Pt | null)[] => {
      const s = pts.map((p) => (p ? toScreen(p) : null));
      return s.map((p, i) => {
        if (!p) return null;
        const prev = s[Math.max(0, i - 1)] ?? p;
        const next = s[Math.min(s.length - 1, i + 1)] ?? p;
        const dx = next[0] - prev[0];
        const dy = next[1] - prev[1];
        const len = Math.hypot(dx, dy) || 1;
        return [p[0] - (dy / len) * OFFSET_PX * sign, p[1] + (dx / len) * OFFSET_PX * sign];
      });
    };

    const strokeSegments = (pts: (Pt | null)[], colorAt: (i: number) => string, width: number) => {
      ctx.lineWidth = width;
      for (let i = 1; i < pts.length; i++) {
        const p0 = pts[i - 1];
        const p1 = pts[i];
        if (!p0 || !p1) continue;
        ctx.strokeStyle = colorAt(i);
        ctx.beginPath();
        ctx.moveTo(p0[0], p0[1]);
        ctx.lineTo(p1[0], p1[1]);
        ctx.stroke();
      }
    };

    const inputColor = (tr: Trace, i: number) =>
      (tr.brake[i] ?? 0) > 0 ? INPUTS.brake : (tr.throttle[i] ?? 0) >= 98 ? INPUTS.full : INPUTS.partial;

    if (colorBy === "faster" && delta && a) {
      const centre = ptsA.map((p) => (p ? toScreen(p) : null));
      strokeSegments(centre, (i) => {
        const k0 = Math.floor(i / FASTER_SEGMENT) * FASTER_SEGMENT;
        const k1 = Math.min(delta.length - 1, k0 + FASTER_SEGMENT);
        const d0 = delta[k0];
        const d1 = delta[k1];
        if (d0 === null || d1 === null || Math.abs(d1 - d0) < FASTER_EPS_S) return INPUTS.partial;
        return d1 > d0 ? DRIVER.a : DRIVER.b; // Δ = t_B − t_A rising → B losing → A faster
      }, 5);
    } else {
      ([[a, ptsA, 1, DRIVER.a], [b, ptsB, -1, DRIVER.b]] as const).forEach(([tr, pts, sign, col]) => {
        if (!tr) return;
        const path = offsetPath(pts, sign);
        if (colorBy === "driver") strokeSegments(path, () => col, 2.5);
        else if (colorBy === "speed") strokeSegments(path, (i) => speedColor(tr.speed[i] ?? 0, speedRange[0], speedRange[1]), 3);
        else strokeSegments(path, (i) => inputColor(tr, i), 3);
      });
    }

    // Start/finish line marker.
    const sf = scr[0];
    ctx.fillStyle = "#f0efec";
    ctx.fillRect(sf[0] - 2, sf[1] - 2, 4, 4);

    // Corner labels, offset along MultiViewer's label angle when available.
    ctx.font = "10px ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const c of track.corners) {
      const [cx, cy] = rotate(c.x, c.y, rot);
      let lp: Pt = [cx, cy];
      if (c.angle !== null) {
        const [ox, oy] = rotate(...rotate(600, 0, c.angle), rot);
        lp = [cx + ox, cy + oy];
      }
      const p = toScreen([cx, cy]);
      const q = toScreen(lp);
      ctx.strokeStyle = "#52514e";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(p[0], p[1]);
      ctx.lineTo(q[0], q[1]);
      ctx.stroke();
      ctx.fillStyle = "#c3c2b7";
      ctx.fillText(`${c.number}${c.letter}`, q[0], q[1]);
    }

    // Cursor markers at the shared distance, each on its own (offset) trace.
    if (cursorS !== null) {
      ([[a, ptsA, 1, DRIVER.a], [b, ptsB, -1, DRIVER.b]] as const).forEach(([tr, pts, sign, col]) => {
        if (!tr) return;
        const i = gridIndex(tr, cursorS);
        const p = offsetPath(pts.slice(Math.max(0, i - 1), i + 2), sign)[Math.min(1, i)];
        if (!p) return;
        ctx.fillStyle = col;
        ctx.strokeStyle = "#1a1a19";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(p[0], p[1], 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
    }
  }, [a, b, ptsA, ptsB, refPts, toScreen, size, colorBy, delta, speedRange, track.corners, rot, cursorS]);

  const drawRef = useRef(draw);
  useEffect(() => {
    drawRef.current = draw;
    draw();
  }, [draw]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.floor(e.contentRect.width), h: 520 }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = size.w * dpr;
    cv.height = size.h * dpr;
    const z = d3zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([1, 40])
      .on("zoom", (e) => {
        transformRef.current = e.transform;
        drawRef.current();
      });
    zoomRef.current = z;
    select(cv).call(z);
    return () => {
      select(cv).on(".zoom", null);
    };
  }, [size]);

  const zoomToCorner = (c: Corner | null) => {
    const cv = canvasRef.current;
    const z = zoomRef.current;
    if (!cv || !z) return;
    if (!c) {
      select(cv).call(z.transform, zoomIdentity);
      setXRange(null);
      return;
    }
    const L = track.reference.length_m;
    const near = track.reference.s
      .map((s, i) => [s, i] as const)
      .filter(([s]) => Math.abs(((s - c.s + L * 1.5) % L) - L / 2) < CORNER_WINDOW_M)
      .map(([, i]) => base(refPts[i]));
    const xs = near.map((p) => p[0]);
    const ys = near.map((p) => p[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const k = Math.min(40, 0.8 * Math.min(size.w / (x1 - x0 || 1), size.h / (y1 - y0 || 1)));
    const t = zoomIdentity.translate(size.w / 2, size.h / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    select(cv).call(z.transform, t);
    setXRange([Math.max(0, c.s - CORNER_WINDOW_M), Math.min(L, c.s + CORNER_WINDOW_M)]);
  };

  const onMove = (e: React.MouseEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best = -1;
    let bestD = 30 * 30;
    refPts.forEach((p, i) => {
      const [x, y] = toScreen(p);
      const d = (x - mx) ** 2 + (y - my) ** 2;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    if (best >= 0) setCursorS(track.reference.s[best]);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex overflow-hidden rounded border border-border">
          {COLOR_MODES.map((m) => (
            <button key={m.id} onClick={() => setColorBy(m.id)}
              className={`px-2 py-1 text-xs ${colorBy === m.id ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink-2"}`}>
              {m.label}
            </button>
          ))}
        </div>
        <Legend colorBy={colorBy} speedRange={speedRange} labels={labels} />
      </div>

      <div ref={wrapRef} className="relative rounded border border-border bg-surface-1">
        <canvas ref={canvasRef} style={{ width: size.w, height: size.h, cursor: "crosshair" }} onMouseMove={onMove} />
        <div className="pointer-events-none absolute left-2 top-2 text-[10px] text-ink-3">scroll to zoom · drag to pan</div>
      </div>

      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-1 text-[10px] uppercase tracking-wider text-ink-3">Zoom to corner</span>
        <button onClick={() => zoomToCorner(null)} className="rounded border border-border px-2 py-0.5 text-xs text-ink-2 hover:text-ink">
          Full lap
        </button>
        {track.corners.map((c) => (
          <button key={`${c.number}${c.letter}`} onClick={() => zoomToCorner(c)}
            className="rounded border border-border px-2 py-0.5 font-mono text-xs text-ink-2 hover:text-ink">
            T{c.number}{c.letter}
          </button>
        ))}
      </div>

      <p className="text-[11px] leading-snug text-ink-3">
        <Badge tier="M" note="Position samples ~4 Hz" /> Traces are drawn {OFFSET_PX * 2}px apart for visibility. Public F1
        position data is map-matched to a single track line, so <b className="text-ink-2">lateral racing-line differences are
        not measurable</b>; differences shown here are <i>where along the lap</i> drivers brake, lift and accelerate.
        Reference line: car {track.reference.driver_number} lap {track.reference.lap_number} ({track.reference.length_m} m).
        Corners: {track.corners[0]?.source ?? "n/a"}.
        {track.notes.map((n) => ` ${n}`)}
      </p>
    </div>
  );
}

function Legend({ colorBy, speedRange, labels }: { colorBy: ColorBy; speedRange: number[]; labels: { a: string; b: string } }) {
  const sw = (c: string) => <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: c }} />;
  if (colorBy === "speed")
    return (
      <div className="flex items-center gap-2 text-[11px] text-ink-2">
        <span>{Math.round(speedRange[0])} km/h</span>
        <span className="h-2 w-32 rounded-sm" style={{ background: `linear-gradient(90deg, ${SPEED_RAMP.join(",")})` }} />
        <span>{Math.round(speedRange[1])} km/h</span>
        <span className="text-ink-3">· A ({labels.a}) right, B ({labels.b}) left of travel direction</span>
      </div>
    );
  if (colorBy === "inputs")
    return (
      <div className="flex items-center gap-3 text-[11px] text-ink-2">
        <span className="flex items-center gap-1">{sw(INPUTS.brake)} brake on</span>
        <span className="flex items-center gap-1">{sw(INPUTS.partial)} partial / coast</span>
        <span className="flex items-center gap-1">{sw(INPUTS.full)} throttle ≥ 98%</span>
      </div>
    );
  if (colorBy === "faster")
    return (
      <div className="flex items-center gap-3 text-[11px] text-ink-2">
        <span className="flex items-center gap-1">{sw(DRIVER.a)} {labels.a} faster</span>
        <span className="flex items-center gap-1">{sw(DRIVER.b)} {labels.b} faster</span>
        <span className="flex items-center gap-1">{sw(INPUTS.partial)} &lt; 10 ms</span>
        <Badge tier="C" note="Per 50 m segment, from the distance-aligned time delta" />
      </div>
    );
  return (
    <div className="flex items-center gap-3 text-[11px] text-ink-2">
      <span className="flex items-center gap-1">{sw(DRIVER.a)} A · {labels.a}</span>
      <span className="flex items-center gap-1">{sw(DRIVER.b)} B · {labels.b}</span>
    </div>
  );
}
