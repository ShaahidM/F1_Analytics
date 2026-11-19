// Small shared UI primitives so every view uses the same card, loading and callout treatment.

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      aria-hidden
      className="inline-block rounded-full border-2 border-border-strong border-t-ink-2"
      style={{ width: size, height: size, animation: "spin 0.8s linear infinite" }}
    />
  );
}

export function Loading({ text, detail }: { text: string; detail?: string }) {
  return (
    <div role="status" className="card flex items-center gap-3 p-4 text-sm text-ink-2">
      <Spinner />
      <div>
        <div>{text}</div>
        {detail && <div className="text-xs text-ink-3">{detail}</div>}
      </div>
    </div>
  );
}

export function Callout({ tone = "info", title, children }: { tone?: "info" | "warn"; title?: string; children: React.ReactNode }) {
  const warn = tone === "warn";
  return (
    <div role={warn ? "alert" : "note"}
      className={`flex gap-2.5 rounded-lg border px-3 py-2 text-xs leading-relaxed ${warn ? "border-warn/35 bg-warn/[0.06] text-ink-2" : "border-border bg-surface-1 text-ink-2"}`}>
      <span aria-hidden className={`mt-px font-semibold ${warn ? "text-warn" : "text-ink-3"}`}>{warn ? "!" : "i"}</span>
      <div>
        {title && <div className={`font-semibold ${warn ? "text-warn" : "text-ink"}`}>{title}</div>}
        {children}
      </div>
    </div>
  );
}

export function Chip({ ok, children, title }: { ok?: boolean; children: React.ReactNode; title?: string }) {
  return (
    <span title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${ok === false ? "border-border text-ink-3 line-through decoration-ink-3/60" : "border-border-strong text-ink-2"}`}>
      {ok !== undefined && <span aria-hidden>{ok ? "✓" : "–"}</span>}
      {children}
    </span>
  );
}

export function SectionHeader({ title, description, right }: { title: string; description?: string; right?: React.ReactNode }) {
  return (
    <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {description && <p className="max-w-3xl text-xs text-ink-3">{description}</p>}
      </div>
      {right}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { id: T; label: string; disabled?: string | null }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
      {options.map((o) => (
        <button key={o.id} role="tab" aria-selected={value === o.id} disabled={!!o.disabled} title={o.disabled ?? undefined}
          onClick={() => onChange(o.id)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35 ${value === o.id ? "bg-surface-3 text-ink shadow-sm" : "text-ink-3 hover:text-ink-2"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
