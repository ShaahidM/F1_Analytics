// Evidence-tier badge (docs/TYRE_METHODOLOGY.md §1). Shown on every metric.

const TIERS = {
  M: { label: "Measured", title: "Directly from the timing feed (resampled only)" },
  C: { label: "Calculated", title: "Deterministic calculation from measured data" },
  E: { label: "Estimated", title: "Statistical model output; carries uncertainty" },
  I: { label: "Interpretation", title: "Hypothesis consistent with the data, not a measurement" },
  A: { label: "Assumption", title: "Unverified assumption chosen by the analyst, not derived from data" },
} as const;

export function Badge({ tier, note }: { tier: keyof typeof TIERS; note?: string }) {
  const t = TIERS[tier];
  return (
    <span
      title={note ? `${t.title}. ${note}` : t.title}
      className="inline-flex h-[18px] cursor-help items-center rounded border border-border px-1.5 align-middle text-[10px] font-medium normal-case tracking-normal text-ink-2"
    >
      {t.label}
    </span>
  );
}
