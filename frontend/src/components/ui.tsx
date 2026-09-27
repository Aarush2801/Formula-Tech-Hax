"use client";

import { AlertTriangle, ChevronDown, Info, Loader2 } from "lucide-react";
import React from "react";

/* ------------------------------------------------------------------ Panel --- */

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
  bodyClassName = "",
  dense = false,
  note,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  dense?: boolean;
  note?: string;
}) {
  return (
    <section
      className={`rounded-md border border-line bg-surface-1/90 backdrop-blur-[1px] ${className}`}
    >
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-3.5 py-2.5">
          <div className="min-w-0">
            {title && (
              <h2 className="label-xs !text-[10.5px] !text-ink-2 truncate">{title}</h2>
            )}
            {subtitle && (
              <p className="mt-1 text-[11.5px] leading-snug text-ink-3">{subtitle}</p>
            )}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
      )}
      <div className={`${dense ? "p-2.5" : "p-3.5"} ${bodyClassName}`}>{children}</div>
      {note && (
        <footer className="border-t border-line px-3.5 py-2">
          <p className="text-[10.5px] leading-relaxed text-ink-3">{note}</p>
        </footer>
      )}
    </section>
  );
}

/* --------------------------------------------------------------- StatTile --- */

/**
 * A single headline number. Per the data-viz form heuristic, one value with no
 * series is a stat tile, not a chart; the optional sparkline is context, not the
 * subject.
 */
export function StatTile({
  label,
  value,
  unit,
  hint,
  tone = "default",
  sub,
  glyph,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: string;
  tone?: "default" | "warning" | "serious" | "critical" | "good" | "accent";
  sub?: React.ReactNode;
  glyph?: string;
  className?: string;
}) {
  const toneColor =
    tone === "warning"
      ? "var(--warning)"
      : tone === "serious"
      ? "var(--serious)"
      : tone === "critical"
      ? "var(--critical)"
      : tone === "good"
      ? "var(--good)"
      : tone === "accent"
      ? "var(--accent)"
      : "var(--text-primary)";
  return (
    <div
      className={`rounded-md border border-line bg-surface-1/90 px-3.5 py-3 ${className}`}
      title={hint}
    >
      <div className="flex items-center gap-1.5">
        <span className="label-xs">{label}</span>
        {hint && <Info size={10} className="text-ink-3 shrink-0" aria-hidden />}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        {glyph && (
          <span className="num text-[15px]" style={{ color: toneColor }} aria-hidden>
            {glyph}
          </span>
        )}
        <span
          className="num text-[26px] leading-none font-medium"
          style={{ color: toneColor }}
        >
          {value}
        </span>
        {unit && <span className="text-[11px] text-ink-3">{unit}</span>}
      </div>
      {sub && <div className="mt-1.5 text-[11px] leading-snug text-ink-3">{sub}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Badge --- */

export function Badge({
  children,
  color,
  glyph,
  title,
  className = "",
}: {
  children: React.ReactNode;
  color?: string;
  glyph?: string;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-[2px] text-[10px] font-semibold uppercase tracking-wider ${className}`}
      style={{
        color: color ?? "var(--text-secondary)",
        borderColor: color ? `${color}55` : "var(--border-strong)",
        background: color ? `${color}14` : "transparent",
      }}
    >
      {glyph && <span aria-hidden>{glyph}</span>}
      {children}
    </span>
  );
}

/* ------------------------------------------------------- States & wrappers --- */

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-8 text-ink-3" role="status">
      <Loader2 size={14} className="animate-spin" aria-hidden />
      <span className="text-xs">{label}…</span>
    </div>
  );
}

export function Skeleton({ h = 120 }: { h?: number }) {
  return (
    <div
      className="relative overflow-hidden rounded border border-line bg-surface-2/40"
      style={{ height: h }}
      aria-hidden
    >
      <div className="sweep absolute inset-y-0 w-1/4 bg-gradient-to-r from-transparent via-white/[0.04] to-transparent" />
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div
      className="rounded-md border px-3.5 py-3"
      style={{ borderColor: "var(--critical)55", background: "var(--critical)0e" }}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle
          size={14}
          className="mt-0.5 shrink-0"
          style={{ color: "var(--critical)" }}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold" style={{ color: "var(--critical)" }}>
            Request failed
          </p>
          <p className="mt-1 break-words font-mono text-[11px] leading-relaxed text-ink-2">
            {msg}
          </p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-2 rounded border border-line-strong px-2 py-1 text-[11px] text-ink-2 hover:bg-surface-2"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-line-strong px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink-2">{title}</p>
      {body && <p className="max-w-md text-[12px] leading-relaxed text-ink-3">{body}</p>}
      {action}
    </div>
  );
}

/* ------------------------------------------------------------- Disclaimer --- */

/**
 * Renders a caveat string supplied by the API. The UI never writes its own
 * wording for what the numbers mean — it shows what the backend says they are.
 */
export function Caveat({
  children,
  tone = "muted",
}: {
  children: React.ReactNode;
  tone?: "muted" | "strong";
}) {
  return (
    <p
      className={`flex gap-1.5 text-[10.5px] leading-relaxed ${
        tone === "strong" ? "text-ink-2" : "text-ink-3"
      }`}
    >
      <Info size={11} className="mt-[2px] shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/* ---------------------------------------------------------------- Controls --- */

export function Select({
  label,
  value,
  onChange,
  options,
  className = "",
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      {label && <span className="label-xs">{label}</span>}
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full appearance-none rounded border border-line-strong bg-surface-2 py-1.5 pl-2 pr-7 text-[12px] text-ink hover:border-[color:var(--accent)]"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={12}
          className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-ink-3"
          aria-hidden
        />
      </div>
    </label>
  );
}

export function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  format,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5" title={hint}>
      <span className="flex items-baseline justify-between gap-2">
        <span className="label-xs">{label}</span>
        <span className="num text-[11.5px] text-ink">
          {format ? format(value) : value}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 w-full cursor-pointer appearance-none rounded bg-surface-3 accent-[color:var(--accent)]"
        aria-label={label}
      />
    </label>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2" title={hint}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className="relative h-4 w-7 shrink-0 rounded-full border transition-colors"
        style={{
          background: checked ? "var(--accent)" : "var(--surface-3)",
          borderColor: checked ? "var(--accent)" : "var(--border-strong)",
        }}
      >
        <span
          className="absolute top-[1px] h-[12px] w-[12px] rounded-full bg-white transition-all"
          style={{ left: checked ? 13 : 1 }}
        />
      </button>
      <span className="text-[12px] text-ink-2">{label}</span>
    </label>
  );
}

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; title?: string }[];
  label?: string;
  size?: "sm" | "md";
}) {
  return (
    <div className="flex flex-col gap-1">
      {label && <span className="label-xs">{label}</span>}
      <div
        className="inline-flex rounded border border-line-strong bg-surface-2 p-[2px]"
        role="tablist"
        aria-label={label}
      >
        {options.map((o) => {
          const active = o.value === value;
          return (
            <button
              key={o.value}
              role="tab"
              aria-selected={active}
              title={o.title}
              onClick={() => onChange(o.value)}
              className={`rounded-[3px] ${
                size === "sm" ? "px-1.5 py-[3px] text-[10.5px]" : "px-2.5 py-1 text-[11.5px]"
              } font-medium transition-colors ${
                active
                  ? "bg-surface-3 text-ink"
                  : "text-ink-3 hover:text-ink-2"
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled,
  size = "md",
  className = "",
  type = "button",
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "ghost" | "danger";
  disabled?: boolean;
  size?: "sm" | "md";
  className?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45";
  const sizes = size === "sm" ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-[12px]";
  const variants = {
    default: "border border-line-strong bg-surface-2 text-ink-2 hover:bg-surface-3 hover:text-ink",
    primary:
      "border border-[color:var(--accent)] bg-[color:var(--accent)]/15 text-[color:var(--accent)] hover:bg-[color:var(--accent)]/25",
    ghost: "text-ink-3 hover:bg-surface-2 hover:text-ink-2",
    danger:
      "border border-[color:var(--critical)]/55 bg-[color:var(--critical)]/10 text-[color:var(--critical)] hover:bg-[color:var(--critical)]/20",
  }[variant];
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${sizes} ${variants} ${className}`}
    >
      {children}
    </button>
  );
}

/* --------------------------------------------------------------- KeyValue --- */

export function KeyValue({
  rows,
  cols = 1,
}: {
  rows: { label: string; value: React.ReactNode; hint?: string }[];
  cols?: 1 | 2 | 3;
}) {
  return (
    <dl
      className={`grid gap-x-5 gap-y-2 ${
        cols === 3 ? "grid-cols-3" : cols === 2 ? "grid-cols-2" : "grid-cols-1"
      }`}
    >
      {rows.map((r, i) => (
        <div key={i} className="min-w-0" title={r.hint}>
          <dt className="label-xs">{r.label}</dt>
          <dd className="num mt-0.5 truncate text-[12.5px] text-ink">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ----------------------------------------------------------------- Table --- */

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  width?: string;
  render: (row: T, i: number) => React.ReactNode;
  sortValue?: (row: T) => number | string;
  title?: string;
}

export function DataTable<T>({
  columns,
  rows,
  onRowClick,
  selectedKey,
  rowKey,
  maxHeight,
  empty = "No rows",
  compact = false,
}: {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: (row: T, i: number) => void;
  selectedKey?: string;
  rowKey?: (row: T, i: number) => string;
  maxHeight?: number;
  empty?: string;
  compact?: boolean;
}) {
  const [sort, setSort] = React.useState<{ key: string; dir: 1 | -1 } | null>(null);
  const sorted = React.useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    return [...rows].sort((a, b) => {
      const va = col.sortValue!(a);
      const vb = col.sortValue!(b);
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * sort.dir;
      return String(va).localeCompare(String(vb)) * sort.dir;
    });
  }, [rows, sort, columns]);

  if (!rows.length) {
    return <p className="px-1 py-6 text-center text-[12px] text-ink-3">{empty}</p>;
  }

  return (
    <div
      className="overflow-auto"
      style={maxHeight ? { maxHeight } : undefined}
    >
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 z-10 bg-surface-1">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                title={c.title}
                style={{ width: c.width }}
                className={`border-b border-line-strong px-2 py-1.5 ${
                  c.align === "right" ? "text-right" : "text-left"
                } label-xs !text-[9.5px] whitespace-nowrap ${
                  c.sortValue ? "cursor-pointer select-none hover:text-ink-2" : ""
                }`}
                onClick={
                  c.sortValue
                    ? () =>
                        setSort((s) =>
                          s?.key === c.key
                            ? { key: c.key, dir: s.dir === 1 ? -1 : 1 }
                            : { key: c.key, dir: -1 }
                        )
                    : undefined
                }
                aria-sort={
                  sort?.key === c.key
                    ? sort.dir === 1
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                {c.header}
                {sort?.key === c.key && (
                  <span className="ml-1 text-ink-2">{sort.dir === 1 ? "↑" : "↓"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const k = rowKey?.(row, i) ?? String(i);
            const selected = selectedKey !== undefined && selectedKey === k;
            return (
              <tr
                key={k}
                onClick={onRowClick ? () => onRowClick(row, i) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row, i);
                        }
                      }
                    : undefined
                }
                className={`border-b border-line/60 ${
                  onRowClick ? "cursor-pointer hover:bg-surface-2" : ""
                } ${selected ? "bg-surface-3" : ""}`}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`px-2 ${compact ? "py-1" : "py-1.5"} ${
                      c.align === "right" ? "num text-right" : "text-left"
                    } text-ink-2`}
                  >
                    {c.render(row, i)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------- Tabs --- */

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { value: T; label: string; count?: number }[];
  active: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-0.5 border-b border-line" role="tablist">
      {tabs.map((t) => {
        const on = t.value === active;
        return (
          <button
            key={t.value}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.value)}
            className={`relative px-3 py-2 text-[12px] font-medium transition-colors ${
              on ? "text-ink" : "text-ink-3 hover:text-ink-2"
            }`}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="num ml-1.5 text-[10.5px] text-ink-3">{t.count}</span>
            )}
            {on && (
              <span
                className="absolute inset-x-2 -bottom-[1px] h-[2px] rounded-full"
                style={{ background: "var(--accent)" }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
