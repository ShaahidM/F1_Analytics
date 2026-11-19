"use client";

import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";
import { Badge } from "./Badge";
import { Segmented } from "./ui";

export function AppHeader() {
  const { view, setView } = useStore();
  const [about, setAbout] = useState(false);
  return (
    <header className="flex flex-wrap items-center gap-4 border-b border-border bg-surface-1 px-5 py-2.5">
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="h-6 w-1.5 rounded-full bg-brand" />
        <div>
          <div className="text-sm font-semibold tracking-tight">F1 Telemetry Lab</div>
          <div className="text-[11px] text-ink-3">Driver comparison &amp; tyre-management analysis</div>
        </div>
      </div>
      <Segmented label="Analysis mode" value={view} onChange={setView}
        options={[{ id: "session", label: "Session analysis" }, { id: "season", label: "Season comparison" }]} />
      <button className="btn ml-auto" onClick={() => setAbout(true)}>About the data</button>
      {about && <AboutPanel onClose={() => setAbout(false)} />}
    </header>
  );
}

function AboutPanel({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label="About the data"
        className="h-full w-full max-w-md overflow-y-auto border-l border-border bg-surface-1 p-5 text-xs leading-relaxed text-ink-2"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">About the data</h2>
          <button className="btn" onClick={onClose} aria-label="Close">Close</button>
        </div>

        <h3 className="eyebrow mb-1.5">Evidence labels</h3>
        <ul className="mb-4 space-y-1.5">
          <li><Badge tier="M" /> straight from the timing feed (speed, throttle, lap times…)</li>
          <li><Badge tier="C" /> calculated from measured data (brake points, deceleration, gaps…)</li>
          <li><Badge tier="E" /> statistical estimate with a confidence interval (tyre-wear cost, trends)</li>
          <li><Badge tier="I" /> interpretation: a pattern the data is consistent with, never a fact</li>
          <li><Badge tier="A" /> assumption chosen by you or the model, not derived from data</li>
        </ul>

        <h3 className="eyebrow mb-1.5">Sources</h3>
        <ul className="mb-4 list-disc space-y-1 pl-4">
          <li><b className="text-ink">OpenF1</b>: 2023 onwards, telemetry at ~4 samples a second, laps, tyres, race control.</li>
          <li><b className="text-ink">Jolpica-F1</b>: 2019–2022, lap times and pit stops only (F1&apos;s archive needs a paid F1 TV subscription).</li>
          <li><b className="text-ink">MultiViewer</b>: corner positions and pit-loss references.</li>
        </ul>

        <h3 className="eyebrow mb-1.5">What the data can&apos;t tell you</h3>
        <ul className="list-disc space-y-1 pl-4">
          <li>Tyre temperature, pressure, wear or grip: nothing here measures tyre state directly.</li>
          <li>The exact racing line: positions are snapped to one track line. Corner &ldquo;line length&rdquo; is an experimental proxy that can&apos;t separate a longer line from tyre slip.</li>
          <li>Brake pressure (brake is on/off only), fuel load, battery deployment and set-up.</li>
          <li>Practice fuel loads, so practice pace isn&apos;t a race-pace ranking.</li>
          <li>Tyre-age effects in wet or drying conditions.</li>
        </ul>
        <p className="mt-4 text-ink-3">The full list is in <code>docs/LIMITATIONS.md</code> in the project repository.</p>
      </aside>
    </div>
  );
}
