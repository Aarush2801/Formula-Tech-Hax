"use client";

/**
 * Chart primitives, hand-built on SVG with d3-scale.
 *
 * Conventions applied throughout, from the data-viz method:
 *   • one y-axis, ever — no dual-axis charts
 *   • thin marks; 4 px rounded data-ends anchored to the baseline; 2 px lines
 *   • a 2 px surface-coloured gap between adjacent fills and stacked segments,
 *     and a 2 px surface ring on overlapping marks
 *   • recessive grid and axes (both below 1.6:1 against the surface)
 *   • a hover layer by default: crosshair + tooltip on lines, per-mark tooltip
 *     on bars, dots and cells
 *   • a legend whenever there are ≥ 2 series, plus direct labels when ≤ 4;
 *     identity is never carried by colour alone
 *   • values are rendered selectively, never one number per point
 */

import { scaleBand, scaleLinear, scalePoint } from "d3-scale";
import { line as d3line, area as d3area, curveMonotoneX } from "d3-shape";
import React from "react";

import { seqColor } from "../../lib/theme";

const SURFACE = "var(--surface-1)";
const GRID = "var(--grid)";
const AXIS = "var(--axis)";
const MUTED = "var(--text-muted)";
const INK2 = "var(--text-secondary)";

/* ---------------------------------------------------------------- Tooltip --- */

export interface TipRow {
  label: string;
  value: string;
  color?: string;
  glyph?: string;
}

export function ChartTooltip({
  x,
  y,
  title,
  rows,
  note,
  containerWidth,
}: {
  x: number;
  y: number;
  title: string;
  rows: TipRow[];
  note?: string;
  containerWidth: number;
}) {
  const W = 216;
  const flip = x + W + 16 > containerWidth;
  return (
    <div
      className="pointer-events-none absolute z-30 rounded border border-line-strong bg-surface-2/97 px-2.5 py-2 shadow-xl backdrop-blur"
      style={{
        left: flip ? x - W - 10 : x + 10,
        top: Math.max(y - 8, 2),
        width: W,
      }}
      role="tooltip"
    >
      <p className="mb-1.5 text-[11px] font-semibold leading-tight text-ink">{title}</p>
      <div className="flex flex-col gap-[3px]">
        {rows.map((r, i) => (
          <div key={i} className="flex items-baseline justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              {r.color && (
                <span
                  className="inline-block h-[7px] w-[7px] shrink-0 rounded-[1px]"
                  style={{ background: r.color }}
                  aria-hidden
                />
              )}
              {r.glyph && (
                <span className="num text-[10px] text-ink-3" aria-hidden>
                  {r.glyph}
                </span>
              )}
              <span className="truncate text-[10.5px] text-ink-3">{r.label}</span>
            </span>
            <span className="num shrink-0 text-[11px] text-ink">{r.value}</span>
          </div>
        ))}
      </div>
      {note && (
        <p className="mt-1.5 border-t border-line pt-1.5 text-[9.5px] leading-snug text-ink-3">
          {note}
        </p>
      )}
    </div>
  );
}

function useTip<T>() {
  const [tip, setTip] = React.useState<{ x: number; y: number; datum: T } | null>(null);
  return { tip, setTip };
}

/* ----------------------------------------------------------------- Legend --- */

export function Legend({
  items,
  className = "",
}: {
  items: { label: string; color: string; glyph?: string; muted?: boolean }[];
  className?: string;
}) {
  return (
    <ul className={`flex flex-wrap items-center gap-x-3 gap-y-1 ${className}`}>
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          <span
            className="inline-block h-[8px] w-[8px] shrink-0 rounded-[1px]"
            style={{ background: it.color, opacity: it.muted ? 0.45 : 1 }}
            aria-hidden
          />
          {it.glyph && (
            <span className="num text-[10px]" style={{ color: it.color }} aria-hidden>
              {it.glyph}
            </span>
          )}
          <span className="text-[10.5px] text-ink-3">{it.label}</span>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------- HBarChart --- */

export interface HBarDatum {
  key: string;
  label: string;
  value: number;
  color?: string;
  glyph?: string;
  secondary?: string;
  tip?: TipRow[];
}

/** Ranked horizontal bars. The default form for "which of these is biggest". */
export function HBarChart({
  data,
  height,
  valueFormat = (v) => v.toFixed(2),
  labelWidth = 150,
  onSelect,
  selectedKey,
  barColor = "var(--series-1)",
  note,
  maxOverride,
  showValues = true,
}: {
  data: HBarDatum[];
  height?: number;
  valueFormat?: (v: number) => string;
  labelWidth?: number;
  onSelect?: (d: HBarDatum) => void;
  selectedKey?: string;
  barColor?: string;
  note?: string;
  maxOverride?: number;
  showValues?: boolean;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(560);
  const { tip, setTip } = useTip<HBarDatum>();

  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const rowH = 20;
  const gap = 2; // the mandated surface gap between adjacent fills
  const H = height ?? data.length * (rowH + gap) + 8;
  const valueW = showValues ? 58 : 6;
  const plotW = Math.max(w - labelWidth - valueW - 8, 40);
  const max = maxOverride ?? Math.max(...data.map((d) => d.value), 1e-9);
  const x = scaleLinear().domain([0, max]).range([0, plotW]).nice();

  return (
    <div ref={ref} className="relative">
      <svg width={w} height={H} role="img" aria-label="Ranked bar chart">
        {x.ticks(4).map((t) => (
          <line
            key={t}
            x1={labelWidth + x(t)}
            x2={labelWidth + x(t)}
            y1={0}
            y2={data.length * (rowH + gap)}
            stroke={GRID}
            strokeWidth={1}
          />
        ))}
        {data.map((d, i) => {
          const y = i * (rowH + gap);
          const bw = Math.max(x(d.value), d.value > 0 ? 2 : 0);
          const sel = selectedKey === d.key;
          return (
            <g
              key={d.key}
              onMouseEnter={(e) =>
                setTip({
                  x: e.nativeEvent.offsetX,
                  y: e.nativeEvent.offsetY,
                  datum: d,
                })
              }
              onMouseMove={(e) =>
                setTip({
                  x: e.nativeEvent.offsetX,
                  y: e.nativeEvent.offsetY,
                  datum: d,
                })
              }
              onMouseLeave={() => setTip(null)}
              onClick={onSelect ? () => onSelect(d) : undefined}
              style={{ cursor: onSelect ? "pointer" : "default" }}
            >
              {/* hit target larger than the mark */}
              <rect x={0} y={y} width={w} height={rowH + gap} fill="transparent" />
              {sel && (
                <rect
                  x={0}
                  y={y - 1}
                  width={w}
                  height={rowH + 2}
                  fill="var(--surface-3)"
                  rx={2}
                />
              )}
              <text
                x={labelWidth - 8}
                y={y + rowH / 2 + 3.5}
                textAnchor="end"
                fontSize={11}
                fill={sel ? "var(--text-primary)" : INK2}
              >
                {d.glyph ? `${d.glyph} ` : ""}
                {d.label.length > 24 ? `${d.label.slice(0, 23)}…` : d.label}
              </text>
              <rect
                x={labelWidth}
                y={y + 4}
                width={bw}
                height={rowH - 8}
                rx={4}
                fill={d.color ?? barColor}
                opacity={sel ? 1 : 0.88}
              />
              {showValues && (
                <text
                  x={labelWidth + plotW + 6}
                  y={y + rowH / 2 + 3.5}
                  fontSize={11}
                  fill={INK2}
                  className="num"
                  textAnchor="start"
                >
                  {valueFormat(d.value)}
                </text>
              )}
            </g>
          );
        })}
        <line
          x1={labelWidth}
          x2={labelWidth}
          y1={0}
          y2={data.length * (rowH + gap)}
          stroke={AXIS}
          strokeWidth={1}
        />
      </svg>
      {tip && (
        <ChartTooltip
          x={tip.x}
          y={tip.y}
          title={tip.datum.label}
          rows={tip.datum.tip ?? [{ label: "Value", value: valueFormat(tip.datum.value) }]}
          note={note}
          containerWidth={w}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------- BarChart --- */

export interface BarDatum {
  key: string;
  label: string;
  value: number;
  color?: string;
  tip?: TipRow[];
  sublabel?: string;
}

/** Vertical bars for an ordered or banded categorical axis. */
export function BarChart({
  data,
  height = 180,
  valueFormat = (v) => v.toFixed(2),
  yLabel,
  barColor = "var(--series-1)",
  onSelect,
  selectedKey,
  note,
  rotateLabels = false,
}: {
  data: BarDatum[];
  height?: number;
  valueFormat?: (v: number) => string;
  yLabel?: string;
  barColor?: string;
  onSelect?: (d: BarDatum) => void;
  selectedKey?: string;
  note?: string;
  rotateLabels?: boolean;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(520);
  const { tip, setTip } = useTip<BarDatum>();
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const m = { top: 10, right: 8, bottom: rotateLabels ? 56 : 26, left: 46 };
  const pw = Math.max(w - m.left - m.right, 40);
  const ph = Math.max(height - m.top - m.bottom, 40);
  const x = scaleBand<string>()
    .domain(data.map((d) => d.key))
    .range([0, pw])
    .paddingInner(0.28)
    .paddingOuter(0.14);
  const maxV = Math.max(...data.map((d) => d.value), 1e-9);
  const y = scaleLinear().domain([0, maxV]).range([ph, 0]).nice();
  const bw = Math.min(x.bandwidth(), 46);

  return (
    <div ref={ref} className="relative">
      <svg width={w} height={height} role="img" aria-label={yLabel ?? "Bar chart"}>
        <g transform={`translate(${m.left},${m.top})`}>
          {y.ticks(4).map((t) => (
            <g key={t}>
              <line x1={0} x2={pw} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text
                x={-7}
                y={y(t) + 3.5}
                textAnchor="end"
                fontSize={10}
                fill={MUTED}
                className="num"
              >
                {valueFormat(t)}
              </text>
            </g>
          ))}
          {data.map((d) => {
            const bx = (x(d.key) ?? 0) + (x.bandwidth() - bw) / 2;
            const h = Math.max(ph - y(d.value), d.value > 0 ? 2 : 0);
            const sel = selectedKey === d.key;
            return (
              <g
                key={d.key}
                onMouseEnter={(e) =>
                  setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, datum: d })
                }
                onMouseMove={(e) =>
                  setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, datum: d })
                }
                onMouseLeave={() => setTip(null)}
                onClick={onSelect ? () => onSelect(d) : undefined}
                style={{ cursor: onSelect ? "pointer" : "default" }}
              >
                <rect x={x(d.key) ?? 0} y={0} width={x.bandwidth()} height={ph} fill="transparent" />
                <rect
                  x={bx}
                  y={y(d.value)}
                  width={bw}
                  height={h}
                  rx={4}
                  fill={d.color ?? barColor}
                  opacity={sel ? 1 : 0.9}
                  stroke={sel ? "var(--text-primary)" : "none"}
                  strokeWidth={sel ? 1 : 0}
                />
              </g>
            );
          })}
          <line x1={0} x2={pw} y1={ph} y2={ph} stroke={AXIS} strokeWidth={1} />
          {data.map((d) => {
            const cx = (x(d.key) ?? 0) + x.bandwidth() / 2;
            return rotateLabels ? (
              <text
                key={d.key}
                transform={`translate(${cx},${ph + 8}) rotate(-38)`}
                textAnchor="end"
                fontSize={10}
                fill={MUTED}
              >
                {d.label.length > 18 ? `${d.label.slice(0, 17)}…` : d.label}
              </text>
            ) : (
              <text
                key={d.key}
                x={cx}
                y={ph + 14}
                textAnchor="middle"
                fontSize={10}
                fill={MUTED}
              >
                {d.label}
              </text>
            );
          })}
        </g>
        {yLabel && (
          <text
            transform={`translate(11,${m.top + ph / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize={9.5}
            fill={MUTED}
            letterSpacing="0.08em"
          >
            {yLabel.toUpperCase()}
          </text>
        )}
      </svg>
      {tip && (
        <ChartTooltip
          x={tip.x}
          y={tip.y}
          title={tip.datum.label}
          rows={tip.datum.tip ?? [{ label: yLabel ?? "Value", value: valueFormat(tip.datum.value) }]}
          note={note}
          containerWidth={w}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------- StackedBarChart --- */

export interface StackSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
}

/** Proportional stacks with a 2 px surface gap between segments. */
export function StackedBarChart({
  categories,
  series,
  height = 190,
  valueFormat = (v) => v.toFixed(0),
  normalise = false,
  note,
  rotateLabels = false,
}: {
  categories: { key: string; label: string }[];
  series: StackSeries[];
  height?: number;
  valueFormat?: (v: number) => string;
  normalise?: boolean;
  note?: string;
  rotateLabels?: boolean;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(520);
  const [tip, setTip] = React.useState<{ x: number; y: number; ci: number } | null>(null);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const m = { top: 10, right: 8, bottom: rotateLabels ? 54 : 26, left: 46 };
  const pw = Math.max(w - m.left - m.right, 40);
  const ph = Math.max(height - m.top - m.bottom, 40);
  const x = scaleBand<string>()
    .domain(categories.map((c) => c.key))
    .range([0, pw])
    .paddingInner(0.3)
    .paddingOuter(0.15);
  const totals = categories.map((_, i) =>
    series.reduce((s, sr) => s + (sr.values[i] ?? 0), 0)
  );
  const maxV = normalise ? 1 : Math.max(...totals, 1e-9);
  const y = scaleLinear().domain([0, maxV]).range([ph, 0]).nice();
  const bw = Math.min(x.bandwidth(), 52);

  return (
    <div ref={ref} className="relative">
      <svg width={w} height={height} role="img" aria-label="Stacked bar chart">
        <g transform={`translate(${m.left},${m.top})`}>
          {y.ticks(4).map((t) => (
            <g key={t}>
              <line x1={0} x2={pw} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text x={-7} y={y(t) + 3.5} textAnchor="end" fontSize={10} fill={MUTED} className="num">
                {normalise ? `${Math.round(t * 100)}%` : valueFormat(t)}
              </text>
            </g>
          ))}
          {categories.map((c, ci) => {
            const bx = (x(c.key) ?? 0) + (x.bandwidth() - bw) / 2;
            const total = totals[ci] || 1;
            let acc = 0;
            return (
              <g
                key={c.key}
                onMouseEnter={(e) =>
                  setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, ci })
                }
                onMouseMove={(e) =>
                  setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, ci })
                }
                onMouseLeave={() => setTip(null)}
              >
                <rect x={x(c.key) ?? 0} y={0} width={x.bandwidth()} height={ph} fill="transparent" />
                {series.map((sr, si) => {
                  const raw = sr.values[ci] ?? 0;
                  const v = normalise ? raw / total : raw;
                  if (v <= 0) return null;
                  const y0 = y(acc);
                  const y1 = y(acc + v);
                  acc += v;
                  const h = Math.max(y0 - y1 - 2, 1); // 2 px surface gap
                  const isTop = si === series.length - 1;
                  return (
                    <rect
                      key={sr.key}
                      x={bx}
                      y={y1}
                      width={bw}
                      height={h}
                      fill={sr.color}
                      rx={isTop ? 4 : 1}
                    />
                  );
                })}
              </g>
            );
          })}
          <line x1={0} x2={pw} y1={ph} y2={ph} stroke={AXIS} strokeWidth={1} />
          {categories.map((c) => {
            const cx = (x(c.key) ?? 0) + x.bandwidth() / 2;
            return rotateLabels ? (
              <text
                key={c.key}
                transform={`translate(${cx},${ph + 8}) rotate(-38)`}
                textAnchor="end"
                fontSize={10}
                fill={MUTED}
              >
                {c.label.length > 18 ? `${c.label.slice(0, 17)}…` : c.label}
              </text>
            ) : (
              <text key={c.key} x={cx} y={ph + 14} textAnchor="middle" fontSize={10} fill={MUTED}>
                {c.label}
              </text>
            );
          })}
        </g>
      </svg>
      {tip && (
        <ChartTooltip
          x={tip.x}
          y={tip.y}
          title={categories[tip.ci].label}
          rows={series
            .map((sr) => ({
              label: sr.label,
              value: valueFormat(sr.values[tip.ci] ?? 0),
              color: sr.color,
            }))
            .filter((r) => r.value !== "0")}
          note={note}
          containerWidth={w}
        />
      )}
      <Legend
        className="mt-2"
        items={series.map((s) => ({ label: s.label, color: s.color }))}
      />
    </div>
  );
}

/* ------------------------------------------------------------- LineChart --- */

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  points: { x: number; y: number | null }[];
  dashed?: boolean;
}

/** Multi-series line chart with a crosshair and a shared tooltip. */
export function LineChart({
  series,
  height = 210,
  xLabel,
  yLabel,
  xFormat = (v) => String(v),
  yFormat = (v) => v.toFixed(2),
  note,
  area = false,
  markers = false,
  yDomain,
  refLines = [],
}: {
  series: LineSeries[];
  height?: number;
  xLabel?: string;
  yLabel?: string;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  note?: string;
  area?: boolean;
  markers?: boolean;
  yDomain?: [number, number];
  refLines?: { y: number; label: string; color?: string }[];
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(560);
  const [hover, setHover] = React.useState<{ x: number; y: number; xi: number } | null>(null);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const m = { top: 12, right: 14, bottom: 30, left: 50 };
  const pw = Math.max(w - m.left - m.right, 40);
  const ph = Math.max(height - m.top - m.bottom, 40);

  const allX = series.flatMap((s) => s.points.map((p) => p.x));
  const allY = series
    .flatMap((s) => s.points.map((p) => p.y))
    .filter((v): v is number => v !== null && Number.isFinite(v));
  const refYs = refLines.map((r) => r.y);
  const x = scaleLinear()
    .domain([Math.min(...allX, 0), Math.max(...allX, 1)])
    .range([0, pw]);
  const y = scaleLinear()
    .domain(yDomain ?? [Math.min(...allY, ...refYs, 0), Math.max(...allY, ...refYs, 1)])
    .range([ph, 0])
    .nice();

  const mkLine = d3line<{ x: number; y: number | null }>()
    .defined((p) => p.y !== null && Number.isFinite(p.y))
    .x((p) => x(p.x))
    .y((p) => y(p.y as number))
    .curve(curveMonotoneX);
  const mkArea = d3area<{ x: number; y: number | null }>()
    .defined((p) => p.y !== null && Number.isFinite(p.y))
    .x((p) => x(p.x))
    .y0(ph)
    .y1((p) => y(p.y as number))
    .curve(curveMonotoneX);

  const xs = series[0]?.points.map((p) => p.x) ?? [];

  const onMove = (e: React.MouseEvent) => {
    const ox = e.nativeEvent.offsetX - m.left;
    if (!xs.length) return;
    const xv = x.invert(Math.max(0, Math.min(ox, pw)));
    let best = 0;
    let bd = Infinity;
    xs.forEach((v, i) => {
      const d = Math.abs(v - xv);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    setHover({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, xi: best });
  };

  return (
    <div ref={ref} className="relative">
      <svg
        width={w}
        height={height}
        role="img"
        aria-label={`${yLabel ?? "Value"} against ${xLabel ?? "x"}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <g transform={`translate(${m.left},${m.top})`}>
          {y.ticks(4).map((t) => (
            <g key={t}>
              <line x1={0} x2={pw} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text x={-7} y={y(t) + 3.5} textAnchor="end" fontSize={10} fill={MUTED} className="num">
                {yFormat(t)}
              </text>
            </g>
          ))}
          {refLines.map((r) => (
            <g key={r.label}>
              <line
                x1={0}
                x2={pw}
                y1={y(r.y)}
                y2={y(r.y)}
                stroke={r.color ?? MUTED}
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <text
                x={pw - 2}
                y={y(r.y) - 4}
                textAnchor="end"
                fontSize={9.5}
                fill={r.color ?? MUTED}
              >
                {r.label}
              </text>
            </g>
          ))}
          {x.ticks(Math.min(6, Math.max(2, xs.length))).map((t) => (
            <text key={t} x={x(t)} y={ph + 14} textAnchor="middle" fontSize={10} fill={MUTED} className="num">
              {xFormat(t)}
            </text>
          ))}

          {area &&
            series.map((s) => (
              <path key={`a-${s.key}`} d={mkArea(s.points) ?? ""} fill={s.color} opacity={0.12} />
            ))}
          {series.map((s) => (
            <path
              key={s.key}
              d={mkLine(s.points) ?? ""}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "5 3" : undefined}
              strokeLinecap="round"
            />
          ))}
          {markers &&
            series.map((s) =>
              s.points.map((p, i) =>
                p.y === null ? null : (
                  <circle
                    key={`${s.key}-${i}`}
                    cx={x(p.x)}
                    cy={y(p.y)}
                    r={4}
                    fill={s.color}
                    stroke={SURFACE}
                    strokeWidth={2}
                  />
                )
              )
            )}

          {hover && xs[hover.xi] !== undefined && (
            <>
              <line
                x1={x(xs[hover.xi])}
                x2={x(xs[hover.xi])}
                y1={0}
                y2={ph}
                stroke={AXIS}
                strokeWidth={1}
              />
              {series.map((s) => {
                const p = s.points[hover.xi];
                if (!p || p.y === null) return null;
                return (
                  <circle
                    key={`h-${s.key}`}
                    cx={x(p.x)}
                    cy={y(p.y)}
                    r={4.5}
                    fill={s.color}
                    stroke={SURFACE}
                    strokeWidth={2}
                  />
                );
              })}
            </>
          )}
          <line x1={0} x2={pw} y1={ph} y2={ph} stroke={AXIS} strokeWidth={1} />
        </g>
        {yLabel && (
          <text
            transform={`translate(11,${m.top + ph / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize={9.5}
            fill={MUTED}
            letterSpacing="0.08em"
          >
            {yLabel.toUpperCase()}
          </text>
        )}
        {xLabel && (
          <text x={m.left + pw / 2} y={height - 2} textAnchor="middle" fontSize={9.5} fill={MUTED} letterSpacing="0.08em">
            {xLabel.toUpperCase()}
          </text>
        )}
      </svg>
      {hover && xs[hover.xi] !== undefined && (
        <ChartTooltip
          x={hover.x}
          y={hover.y}
          title={`${xLabel ?? "x"} ${xFormat(xs[hover.xi])}`}
          rows={series
            .map((s) => {
              const p = s.points[hover.xi];
              return {
                label: s.label,
                value: p && p.y !== null ? yFormat(p.y) : "—",
                color: s.color,
              };
            })}
          note={note}
          containerWidth={w}
        />
      )}
      {series.length >= 2 && (
        <Legend className="mt-2" items={series.map((s) => ({ label: s.label, color: s.color }))} />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Scatter --- */

export interface ScatterPoint {
  x: number;
  y: number;
  key: string;
  label: string;
  color?: string;
  r?: number;
  tip?: TipRow[];
}

export function ScatterChart({
  points,
  height = 240,
  xLabel,
  yLabel,
  xFormat = (v) => v.toFixed(2),
  yFormat = (v) => v.toFixed(2),
  onSelect,
  note,
  refLines = [],
}: {
  points: ScatterPoint[];
  height?: number;
  xLabel?: string;
  yLabel?: string;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  onSelect?: (p: ScatterPoint) => void;
  note?: string;
  refLines?: { y?: number; x?: number; label: string; color?: string }[];
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(560);
  const { tip, setTip } = useTip<ScatterPoint>();
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const m = { top: 12, right: 14, bottom: 32, left: 50 };
  const pw = Math.max(w - m.left - m.right, 40);
  const ph = Math.max(height - m.top - m.bottom, 40);
  const x = scaleLinear()
    .domain([Math.min(...points.map((p) => p.x), 0), Math.max(...points.map((p) => p.x), 1)])
    .range([0, pw])
    .nice();
  const y = scaleLinear()
    .domain([Math.min(...points.map((p) => p.y), 0), Math.max(...points.map((p) => p.y), 1)])
    .range([ph, 0])
    .nice();

  return (
    <div ref={ref} className="relative">
      <svg width={w} height={height} role="img" aria-label={`${yLabel} against ${xLabel}`}>
        <g transform={`translate(${m.left},${m.top})`}>
          {y.ticks(4).map((t) => (
            <g key={`y${t}`}>
              <line x1={0} x2={pw} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text x={-7} y={y(t) + 3.5} textAnchor="end" fontSize={10} fill={MUTED} className="num">
                {yFormat(t)}
              </text>
            </g>
          ))}
          {x.ticks(5).map((t) => (
            <g key={`x${t}`}>
              <line x1={x(t)} x2={x(t)} y1={0} y2={ph} stroke={GRID} strokeWidth={1} />
              <text x={x(t)} y={ph + 14} textAnchor="middle" fontSize={10} fill={MUTED} className="num">
                {xFormat(t)}
              </text>
            </g>
          ))}
          {refLines.map((r) => (
            <g key={r.label}>
              {r.y !== undefined && (
                <line x1={0} x2={pw} y1={y(r.y)} y2={y(r.y)} stroke={r.color ?? MUTED} strokeDasharray="3 3" strokeWidth={1} />
              )}
              {r.x !== undefined && (
                <line x1={x(r.x)} x2={x(r.x)} y1={0} y2={ph} stroke={r.color ?? MUTED} strokeDasharray="3 3" strokeWidth={1} />
              )}
              <text
                x={r.x !== undefined ? x(r.x) + 3 : pw - 2}
                y={r.y !== undefined ? y(r.y) - 4 : 10}
                textAnchor={r.x !== undefined ? "start" : "end"}
                fontSize={9.5}
                fill={r.color ?? MUTED}
              >
                {r.label}
              </text>
            </g>
          ))}
          {points.map((p) => (
            <circle
              key={p.key}
              cx={x(p.x)}
              cy={y(p.y)}
              r={p.r ?? 4.5}
              fill={p.color ?? "var(--series-1)"}
              fillOpacity={0.72}
              stroke={SURFACE}
              strokeWidth={1.5}
              style={{ cursor: onSelect ? "pointer" : "default" }}
              onMouseEnter={(e) =>
                setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, datum: p })
              }
              onMouseLeave={() => setTip(null)}
              onClick={onSelect ? () => onSelect(p) : undefined}
            />
          ))}
          <line x1={0} x2={pw} y1={ph} y2={ph} stroke={AXIS} strokeWidth={1} />
          <line x1={0} x2={0} y1={0} y2={ph} stroke={AXIS} strokeWidth={1} />
        </g>
        {yLabel && (
          <text transform={`translate(11,${m.top + ph / 2}) rotate(-90)`} textAnchor="middle" fontSize={9.5} fill={MUTED} letterSpacing="0.08em">
            {yLabel.toUpperCase()}
          </text>
        )}
        {xLabel && (
          <text x={m.left + pw / 2} y={height - 2} textAnchor="middle" fontSize={9.5} fill={MUTED} letterSpacing="0.08em">
            {xLabel.toUpperCase()}
          </text>
        )}
      </svg>
      {tip && (
        <ChartTooltip
          x={tip.x}
          y={tip.y}
          title={tip.datum.label}
          rows={
            tip.datum.tip ?? [
              { label: xLabel ?? "x", value: xFormat(tip.datum.x) },
              { label: yLabel ?? "y", value: yFormat(tip.datum.y) },
            ]
          }
          note={note}
          containerWidth={w}
        />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Heatmap --- */

export interface HeatCell {
  i: number;
  j: number;
  value: number | null;
  label: string;
  tip?: TipRow[];
  muted?: boolean;
}

/**
 * Matrix heatmap on the single-hue sequential ramp. Cells with no data are drawn
 * as an outline rather than a colour, so "nothing measured" never looks like
 * "measured zero".
 */
export function HeatmapGrid({
  rows,
  cols,
  cells,
  valueFormat = (v) => v.toFixed(3),
  onSelect,
  selected,
  cellSize = 34,
  rowLabelWidth = 118,
  legendLabel,
  note,
}: {
  rows: { key: string; label: string }[];
  cols: { key: string; label: string }[];
  cells: HeatCell[];
  valueFormat?: (v: number) => string;
  onSelect?: (c: HeatCell) => void;
  selected?: { i: number; j: number } | null;
  cellSize?: number;
  rowLabelWidth?: number;
  legendLabel?: string;
  note?: string;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(700);
  const { tip, setTip } = useTip<HeatCell>();
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const vals = cells.map((c) => c.value).filter((v): v is number => v !== null);
  const max = Math.max(...vals, 1e-9);
  const topPad = 76;
  const size = Math.min(
    cellSize,
    Math.max(Math.floor((w - rowLabelWidth - 12) / Math.max(cols.length, 1)), 16)
  );
  const H = topPad + rows.length * size + 6;
  const byIJ = new Map(cells.map((c) => [`${c.i}-${c.j}`, c]));

  return (
    <div ref={ref} className="relative">
      <svg width={w} height={H} role="img" aria-label="Interaction matrix">
        {cols.map((c, j) => (
          <text
            key={c.key}
            transform={`translate(${rowLabelWidth + j * size + size / 2},${topPad - 8}) rotate(-52)`}
            textAnchor="start"
            fontSize={10}
            fill={MUTED}
          >
            {c.label.length > 15 ? `${c.label.slice(0, 14)}…` : c.label}
          </text>
        ))}
        {rows.map((r, i) => (
          <text
            key={r.key}
            x={rowLabelWidth - 8}
            y={topPad + i * size + size / 2 + 3.5}
            textAnchor="end"
            fontSize={10.5}
            fill={INK2}
          >
            {r.label.length > 17 ? `${r.label.slice(0, 16)}…` : r.label}
          </text>
        ))}
        {rows.map((_, i) =>
          cols.map((_, j) => {
            const c = byIJ.get(`${i}-${j}`);
            const x0 = rowLabelWidth + j * size;
            const y0 = topPad + i * size;
            const sel = selected?.i === i && selected?.j === j;
            const hasValue = c && c.value !== null;
            return (
              <g key={`${i}-${j}`}>
                <rect
                  x={x0 + 1}
                  y={y0 + 1}
                  width={size - 2}
                  height={size - 2}
                  rx={2}
                  fill={hasValue ? seqColor((c!.value as number) / max) : "transparent"}
                  stroke={
                    sel
                      ? "var(--text-primary)"
                      : hasValue
                      ? SURFACE
                      : "var(--border-strong)"
                  }
                  strokeWidth={sel ? 2 : hasValue ? 1 : 1}
                  strokeDasharray={hasValue ? undefined : "2 2"}
                  opacity={c?.muted ? 0.45 : 1}
                  style={{ cursor: onSelect && hasValue ? "pointer" : "default" }}
                  onMouseEnter={(e) =>
                    c &&
                    setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, datum: c })
                  }
                  onMouseLeave={() => setTip(null)}
                  onClick={onSelect && c ? () => onSelect(c) : undefined}
                />
                {c?.muted && hasValue && (
                  <text
                    x={x0 + size - 4}
                    y={y0 + 9}
                    textAnchor="end"
                    fontSize={7}
                    fill="var(--text-primary)"
                    opacity={0.8}
                  >
                    ·
                  </text>
                )}
              </g>
            );
          })
        )}
      </svg>
      <div className="mt-2 flex items-center gap-3">
        <RampLegend max={max} label={legendLabel} format={valueFormat} />
        <span className="flex items-center gap-1.5 text-[10px] text-ink-3">
          <span
            className="inline-block h-[9px] w-[9px] rounded-[1px] border border-dashed"
            style={{ borderColor: "var(--border-strong)" }}
            aria-hidden
          />
          no data
        </span>
        <span className="flex items-center gap-1 text-[10px] text-ink-3">
          <span aria-hidden>·</span> sparse
        </span>
      </div>
      {tip && (
        <ChartTooltip
          x={tip.x}
          y={tip.y}
          title={tip.datum.label}
          rows={
            tip.datum.tip ?? [
              {
                label: legendLabel ?? "Value",
                value: tip.datum.value === null ? "—" : valueFormat(tip.datum.value),
              },
            ]
          }
          note={note}
          containerWidth={w}
        />
      )}
    </div>
  );
}

export function RampLegend({
  max,
  min = 0,
  label,
  format = (v) => v.toFixed(2),
  width = 108,
}: {
  max: number;
  min?: number;
  label?: string;
  format?: (v: number) => string;
  width?: number;
}) {
  const stops = 24;
  return (
    <div className="flex items-center gap-2">
      {label && <span className="label-xs">{label}</span>}
      <span className="num text-[10px] text-ink-3">{format(min)}</span>
      <svg width={width} height={8} aria-hidden>
        {Array.from({ length: stops }, (_, i) => (
          <rect
            key={i}
            x={(i * width) / stops}
            y={0}
            width={width / stops + 0.6}
            height={8}
            fill={seqColor(i / (stops - 1))}
          />
        ))}
      </svg>
      <span className="num text-[10px] text-ink-3">{format(max)}</span>
    </div>
  );
}

/* -------------------------------------------------------------- Sparkline --- */

export function Sparkline({
  values,
  width = 90,
  height = 22,
  color = "var(--series-1)",
  fill = true,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
}) {
  const clean = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (clean.length < 2) return <span className="text-[10px] text-ink-3">—</span>;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const x = scaleLinear().domain([0, values.length - 1]).range([1, width - 1]);
  const y = scaleLinear().domain([min, max === min ? min + 1 : max]).range([height - 2, 2]);
  const pts = values.map((v, i) => ({ x: i, y: v }));
  const l = d3line<{ x: number; y: number | null }>()
    .defined((p) => p.y !== null)
    .x((p) => x(p.x))
    .y((p) => y(p.y as number))
    .curve(curveMonotoneX);
  const a = d3area<{ x: number; y: number | null }>()
    .defined((p) => p.y !== null)
    .x((p) => x(p.x))
    .y0(height)
    .y1((p) => y(p.y as number))
    .curve(curveMonotoneX);
  return (
    <svg width={width} height={height} aria-hidden>
      {fill && <path d={a(pts) ?? ""} fill={color} opacity={0.14} />}
      <path d={l(pts) ?? ""} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    </svg>
  );
}

/* ------------------------------------------------------- ProportionRibbon --- */

/** A single normalised stacked bar — for a severity or type mix in one row. */
export function ProportionRibbon({
  parts,
  height = 8,
  totalLabel,
}: {
  parts: { key: string; label: string; value: number; color: string; glyph?: string }[];
  height?: number;
  totalLabel?: string;
}) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!total) return <div className="h-2 rounded bg-surface-3" aria-hidden />;
  return (
    <div>
      <div className="flex gap-[2px]" style={{ height }} role="img" aria-label={totalLabel}>
        {parts
          .filter((p) => p.value > 0)
          .map((p) => (
            <div
              key={p.key}
              title={`${p.label}: ${p.value} (${((p.value / total) * 100).toFixed(1)}%)`}
              style={{
                width: `${(p.value / total) * 100}%`,
                background: p.color,
                borderRadius: 2,
              }}
            />
          ))}
      </div>
    </div>
  );
}
