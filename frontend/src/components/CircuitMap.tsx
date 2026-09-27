"use client";

/**
 * Circuit map.
 *
 * One component serves every screen that draws the track: the hotspot heatmap,
 * the live view, and the replay viewer. It takes the geometry the API computes
 * from the same segment definitions the engine drives on, so what is drawn and
 * what was simulated cannot drift apart.
 *
 * The track is drawn from its real left and right edges (so a narrow corner looks
 * narrow), segment tint uses the single-hue sequential ramp for magnitude, and
 * severity markers carry a glyph as well as a colour.
 */

import React from "react";

import type { HotspotSegment, TrackGeometry } from "../lib/api";
import { SEVERITY, SeverityKey, seqColor } from "../lib/theme";

export interface MapMarker {
  key: string;
  x: number;
  y: number;
  severity?: SeverityKey;
  color?: string;
  label?: string;
  r?: number;
}

export interface MapCar {
  key: string;
  x: number;
  y: number;
  label: string;
  color: string;
  highlight?: boolean;
  dim?: boolean;
  heading?: number;
  braking?: number;
}

export interface CircuitMapProps {
  track: TrackGeometry;
  height?: number;
  /** Per-segment magnitude, normalised internally against its own maximum. */
  segmentValues?: Record<number, number>;
  segmentValueMax?: number;
  onSegmentClick?: (segmentIndex: number) => void;
  selectedSegment?: number | null;
  markers?: MapMarker[];
  cars?: MapCar[];
  /** Fade the track and show only markers/cars — used during replay. */
  focusSegment?: number | null;
  showRacingLine?: boolean;
  showCornerLabels?: boolean;
  showStartLine?: boolean;
  trail?: { x: number[]; y: number[]; color: string }[];
  className?: string;
  padding?: number;
}

export function CircuitMap({
  track,
  height = 420,
  segmentValues,
  segmentValueMax,
  onSegmentClick,
  selectedSegment,
  markers = [],
  cars = [],
  focusSegment = null,
  showRacingLine = true,
  showCornerLabels = true,
  showStartLine = true,
  trail = [],
  className = "",
  padding = 26,
}: CircuitMapProps) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(700);
  const [hoverSeg, setHoverSeg] = React.useState<number | null>(null);

  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  /* --- fit the circuit into the viewport, flipping y (track y is up) ------- */
  const fit = React.useMemo(() => {
    const xs = [...track.edges.left.x, ...track.edges.right.x];
    const ys = [...track.edges.left.y, ...track.edges.right.y];
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const scale = Math.min((w - padding * 2) / spanX, (height - padding * 2) / spanY);
    const offX = padding + (w - padding * 2 - spanX * scale) / 2;
    const offY = padding + (height - padding * 2 - spanY * scale) / 2;
    const tx = (x: number) => offX + (x - minX) * scale;
    const ty = (y: number) => offY + (maxY - y) * scale;
    return { tx, ty, scale };
  }, [track, w, height, padding]);

  const { tx, ty, scale } = fit;

  /* --- the tarmac: left edge forward, right edge back ---------------------- */
  const trackBand = React.useMemo(() => {
    const L = track.edges.left;
    const R = track.edges.right;
    let d = `M ${tx(L.x[0])} ${ty(L.y[0])}`;
    for (let i = 1; i < L.x.length; i++) d += ` L ${tx(L.x[i])} ${ty(L.y[i])}`;
    for (let i = R.x.length - 1; i >= 0; i--) d += ` L ${tx(R.x[i])} ${ty(R.y[i])}`;
    return `${d} Z`;
  }, [track, tx, ty]);

  /* --- per-segment centreline polylines, for tint and hit targets ---------- */
  const segPaths = React.useMemo(() => {
    const cl = track.centreline;
    return track.segments.map((seg) => {
      const pts: string[] = [];
      for (let i = 0; i < cl.s.length; i++) {
        if (cl.s[i] >= seg.s_start - 1 && cl.s[i] <= seg.s_end + 1) {
          pts.push(`${i === 0 || pts.length === 0 ? "M" : "L"} ${tx(cl.x[i])} ${ty(cl.y[i])}`);
        }
      }
      return { index: seg.index, d: pts.join(" "), seg };
    });
  }, [track, tx, ty]);

  const racingLinePath = React.useMemo(() => {
    if (!showRacingLine) return "";
    const cl = track.centreline;
    const rl = track.racing_line;
    const pts: string[] = [];
    for (let i = 0; i < cl.x.length; i++) {
      const d = rl.d[i] ?? 0;
      const h = cl.heading[i] ?? 0;
      const x = cl.x[i] - d * Math.sin(h);
      const y = cl.y[i] + d * Math.cos(h);
      pts.push(`${i === 0 ? "M" : "L"} ${tx(x)} ${ty(y)}`);
    }
    return pts.join(" ");
  }, [track, tx, ty, showRacingLine]);

  const trackWidthPx = Math.max(scale * 15, 3);

  const maxVal = React.useMemo(() => {
    if (!segmentValues) return 0;
    return segmentValueMax ?? Math.max(...Object.values(segmentValues), 1e-9);
  }, [segmentValues, segmentValueMax]);

  return (
    <div ref={ref} className={`relative ${className}`}>
      <svg width={w} height={height} role="img" aria-label={`${track.name} circuit map`}>
        {/* Tarmac. The accurate edge polygon carries the true width — so a narrow
            corner looks narrow — but at circuit zoom that ribbon is only a few
            pixels across, so a base stroke along the centreline underneath
            guarantees the road is legible even where nothing is tinted. */}
        <path
          d={segPaths.map((s) => s.d).join(" ")}
          fill="none"
          stroke="#1c2634"
          strokeWidth={Math.max(trackWidthPx, 5)}
          strokeLinecap="round"
        />
        <path d={trackBand} fill="#1f2a3a" stroke="#32425a" strokeWidth={1.1} />

        {/* segment tint — magnitude on the single-hue sequential ramp */}
        {segmentValues &&
          segPaths.map(({ index, d }) => {
            const v = segmentValues[index] ?? 0;
            if (!d) return null;
            return (
              <path
                key={`tint-${index}`}
                d={d}
                fill="none"
                stroke={v > 0 ? seqColor(v / maxVal) : "transparent"}
                strokeWidth={trackWidthPx}
                strokeLinecap="butt"
                opacity={
                  focusSegment !== null && focusSegment !== index ? 0.25 : v > 0 ? 0.92 : 0
                }
              />
            );
          })}

        {/* centreline */}
        <g opacity={0.5}>
          {segPaths.map(({ index, d }) => (
            <path
              key={`cl-${index}`}
              d={d}
              fill="none"
              stroke="var(--axis)"
              strokeWidth={1}
              strokeDasharray="4 5"
            />
          ))}
        </g>

        {showRacingLine && racingLinePath && (
          <path
            d={racingLinePath}
            fill="none"
            stroke="var(--text-muted)"
            strokeWidth={1.2}
            strokeDasharray="2 4"
            opacity={0.55}
          />
        )}

        {/* trails (replay) */}
        {trail.map((t, ti) => {
          let d = "";
          for (let i = 0; i < t.x.length; i++)
            d += `${i === 0 ? "M" : "L"} ${tx(t.x[i])} ${ty(t.y[i])}`;
          return (
            <path
              key={`trail-${ti}`}
              d={d}
              fill="none"
              stroke={t.color}
              strokeWidth={1.8}
              opacity={0.5}
              strokeLinecap="round"
            />
          );
        })}

        {/* interactive segment hit targets */}
        {onSegmentClick &&
          segPaths.map(({ index, d, seg }) => (
            <path
              key={`hit-${index}`}
              d={d}
              fill="none"
              stroke="transparent"
              strokeWidth={Math.max(trackWidthPx, 14)}
              style={{ cursor: "pointer" }}
              onClick={() => onSegmentClick(index)}
              onMouseEnter={() => setHoverSeg(index)}
              onMouseLeave={() => setHoverSeg(null)}
            >
              <title>{seg.name}</title>
            </path>
          ))}

        {/* selection / hover outline */}
        {[selectedSegment, hoverSeg].map((idx, k) =>
          idx === null || idx === undefined ? null : (
            <path
              key={`sel-${k}-${idx}`}
              d={segPaths[idx]?.d ?? ""}
              fill="none"
              stroke={k === 0 ? "var(--text-primary)" : "var(--accent)"}
              strokeWidth={trackWidthPx + 2}
              opacity={k === 0 ? 0.5 : 0.28}
              strokeLinecap="butt"
            />
          )
        )}

        {/* start / finish */}
        {showStartLine && (
          <g>
            <line
              x1={tx(track.edges.left.x[0])}
              y1={ty(track.edges.left.y[0])}
              x2={tx(track.edges.right.x[0])}
              y2={ty(track.edges.right.y[0])}
              stroke="var(--text-primary)"
              strokeWidth={2}
              opacity={0.75}
            />
            <text
              x={tx(track.centreline.x[0]) + 8}
              y={ty(track.centreline.y[0]) - 6}
              fontSize={9}
              fill="var(--text-muted)"
              letterSpacing="0.08em"
            >
              S/F
            </text>
          </g>
        )}

        {/* corner numbers */}
        {showCornerLabels &&
          track.segments
            .filter((s) => s.corner_radius !== null && s.turn_number !== null)
            .map((s) => {
              const cl = track.centreline;
              let bi = 0;
              let bd = Infinity;
              for (let i = 0; i < cl.s.length; i++) {
                const dd = Math.abs(cl.s[i] - s.s_mid);
                if (dd < bd) {
                  bd = dd;
                  bi = i;
                }
              }
              // Push the label outboard of the corner, away from the apex.
              const h = cl.heading[bi] ?? 0;
              const sign = s.curvature > 0 ? -1 : 1;
              const off = 17 / Math.max(scale, 1e-6);
              const lx = cl.x[bi] - sign * off * Math.sin(h);
              const ly = cl.y[bi] + sign * off * Math.cos(h);
              const isSel = selectedSegment === s.index;
              return (
                <g key={`t-${s.turn_number}`} style={{ pointerEvents: "none" }}>
                  <circle
                    cx={tx(lx)}
                    cy={ty(ly)}
                    r={8.5}
                    fill="var(--surface-1)"
                    stroke={isSel ? "var(--text-primary)" : "var(--border-strong)"}
                    strokeWidth={1}
                  />
                  <text
                    x={tx(lx)}
                    y={ty(ly) + 3.2}
                    textAnchor="middle"
                    fontSize={9}
                    className="num"
                    fill={isSel ? "var(--text-primary)" : "var(--text-secondary)"}
                  >
                    {s.turn_number}
                  </text>
                </g>
              );
            })}

        {/* conflict markers — colour plus glyph */}
        {markers.map((m) => {
          const sev = m.severity ? SEVERITY[m.severity] : null;
          const color = m.color ?? sev?.color ?? "var(--accent)";
          return (
            <g key={m.key} style={{ pointerEvents: "none" }}>
              <circle
                cx={tx(m.x)}
                cy={ty(m.y)}
                r={m.r ?? 3.4}
                fill={color}
                fillOpacity={0.85}
                stroke="var(--surface-1)"
                strokeWidth={1}
              />
            </g>
          );
        })}

        {/* cars */}
        {cars.map((c) => (
          <g key={c.key} style={{ pointerEvents: "none" }}>
            {c.highlight && (
              <circle cx={tx(c.x)} cy={ty(c.y)} r={11} fill={c.color} opacity={0.16} />
            )}
            <circle
              cx={tx(c.x)}
              cy={ty(c.y)}
              r={c.highlight ? 6 : 4.6}
              fill={c.color}
              opacity={c.dim ? 0.4 : 1}
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
            {c.braking !== undefined && c.braking > 0.35 && (
              <circle
                cx={tx(c.x)}
                cy={ty(c.y)}
                r={c.highlight ? 9 : 7.5}
                fill="none"
                stroke="var(--critical)"
                strokeWidth={1.4}
                opacity={Math.min(c.braking, 1)}
              />
            )}
            {c.highlight && (
              <text
                x={tx(c.x)}
                y={ty(c.y) - 12}
                textAnchor="middle"
                fontSize={9.5}
                className="num"
                fill="var(--text-primary)"
              >
                {c.label}
              </text>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}

/** Convert curvilinear (s, d) to the Cartesian frame the map draws in. */
export function toCartesian(
  track: TrackGeometry,
  s: number,
  d: number
): { x: number; y: number } {
  const cl = track.centreline;
  const sm = ((s % track.length) + track.length) % track.length;
  let bi = 0;
  let bd = Infinity;
  for (let i = 0; i < cl.s.length; i++) {
    const dd = Math.abs(cl.s[i] - sm);
    if (dd < bd) {
      bd = dd;
      bi = i;
    }
  }
  const h = cl.heading[bi] ?? 0;
  return { x: cl.x[bi] - d * Math.sin(h), y: cl.y[bi] + d * Math.cos(h) };
}

/** Marker positions for a list of conflicts, jittered within the segment. */
export function conflictMarkers(
  track: TrackGeometry,
  conflicts: { segment_index: number; severity: string; min_ttc: number; run_id: string; driver_a: string }[]
): MapMarker[] {
  const bySeg = new Map(track.segments.map((s) => [s.index, s]));
  return conflicts.map((c, i) => {
    const seg = bySeg.get(c.segment_index);
    // Deterministic pseudo-jitter so a redraw does not move the dots.
    const h = (i * 2654435761) % 1000;
    const frac = 0.15 + 0.7 * (h / 1000);
    const s = seg ? seg.s_start + frac * (seg.s_end - seg.s_start) : 0;
    const lateral = ((((i * 97) % 100) / 100) - 0.5) * (seg ? seg.width * 0.62 : 4);
    const p = toCartesian(track, s, lateral);
    return {
      key: `${c.run_id}-${c.driver_a}-${i}`,
      x: p.x,
      y: p.y,
      severity: (c.severity as SeverityKey) ?? "WARNING",
      label: c.driver_a,
    };
  });
}
