"use client";

import type { Data, Layout } from "plotly.js-dist-min";
import { useEffect, useRef } from "react";

// Shared dark theme matching globals.css tokens; one y-axis per chart (never dual axes).
const BASE_LAYOUT: Partial<Layout> = {
  paper_bgcolor: "#1a1a19",
  plot_bgcolor: "#1a1a19",
  font: { color: "#c3c2b7", size: 12, family: "system-ui, sans-serif" },
  margin: { l: 56, r: 12, t: 28, b: 40 },
  xaxis: { gridcolor: "#2b2b28", zerolinecolor: "#33332f", linecolor: "#33332f" },
  yaxis: { gridcolor: "#2b2b28", zerolinecolor: "#33332f", linecolor: "#33332f" },
  legend: { orientation: "h", y: -0.22, font: { size: 12 } },
  hoverlabel: { bgcolor: "#232321", bordercolor: "#33332f", font: { color: "#f0efec", size: 12 } },
};

// Charts use the page's own sans font (Geist, loaded by next/font under a generated family name).
const pageFont = () => getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";

export function Plot({ data, layout, height = 320 }: { data: Data[]; layout?: Partial<Layout>; height?: number }) {
  const el = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const node = el.current;
    import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (cancelled || !node) return;
      const merged: Partial<Layout> = {
        ...BASE_LAYOUT,
        ...layout,
        font: { ...BASE_LAYOUT.font, family: pageFont(), ...layout?.font },
        legend: { ...BASE_LAYOUT.legend, ...layout?.legend, font: { ...BASE_LAYOUT.legend?.font, ...layout?.legend?.font } },
        height,
        xaxis: { ...BASE_LAYOUT.xaxis, ...layout?.xaxis },
        yaxis: { ...BASE_LAYOUT.yaxis, ...layout?.yaxis },
      };
      Plotly.react(node, data, merged, { displaylogo: false, responsive: true });
    });
    return () => {
      cancelled = true;
    };
  }, [data, layout, height]);

  useEffect(() => {
    const node = el.current;
    return () => {
      if (node) import("plotly.js-dist-min").then(({ default: Plotly }) => Plotly.purge(node));
    };
  }, []);

  return <div ref={el} className="w-full" />;
}
