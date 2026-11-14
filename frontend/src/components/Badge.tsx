// Evidence-tier badge (docs/TYRE_METHODOLOGY.md §1). Shown on every metric.

const TIERS = {
  M: { label: "Measured", title: "Directly from the timing feed (resampled only)" },
  C: { label: "Calculated", title: "Deterministic calculation from measured data" },
  E: { label: "Estimated", title: "Statistical model output; carries uncertainty" },
  I: { label: "Interpretation", title: "Hypothesis consistent with the data, not a measurement" },
} as const;

export function Badge({ tier, note }: { tier: keyof typeof TIERS; note?: string }) {
  const t = TIERS[tier];
  return (
    <span
      title={note ? `${t.title}. ${note}` : t.title}
      className="inline-flex h-4 cursor-help items-center rounded-sm border border-border px-1 font-mono text-[9px] text-ink-2"
    >
      {tier} · {t.label}
    </span>
  );
}
