/**
 * Visual encoding vocabulary.
 *
 * Severity is ordered, so it gets an ordered status ramp (yellow → orange → red)
 * plus a glyph and a label. Nothing in this app communicates severity by hue
 * alone: `SEVERITY[x].glyph` is rendered beside the colour everywhere, which also
 * covers print, forced-colours and colour-vision deficiency.
 *
 * Conflict *counts* use the blue sequential ramp instead of a warm one. A count
 * is a magnitude, not a severity, and tinting a density map red would imply a
 * judgement the number does not support.
 */

export type SeverityKey = "NORMAL" | "WARNING" | "CRITICAL" | "INCIDENT";

export const SEVERITY: Record<
  SeverityKey,
  { label: string; color: string; glyph: string; rank: number; description: string }
> = {
  NORMAL: {
    label: "Normal",
    color: "var(--text-muted)",
    glyph: "○",
    rank: 0,
    description: "Safe following distance; no surrogate measure crossed its threshold.",
  },
  WARNING: {
    label: "Warning",
    color: "var(--warning)",
    glyph: "△",
    rank: 1,
    description:
      "High closing speed, hard braking or a small gap. TTC below the 1.5 s SSAM conflict threshold, or PET below 5 s.",
  },
  CRITICAL: {
    label: "Critical",
    color: "var(--serious)",
    glyph: "◆",
    rank: 2,
    description:
      "Very low TTC (≤ 0.8 s) or a critically low PET with evasive action — conflicting trajectories that forced a response.",
  },
  INCIDENT: {
    label: "Incident",
    color: "var(--critical)",
    glyph: "✕",
    rank: 3,
    description: "Contact, a spin, or an off-track excursion occurred.",
  },
};

export const SEVERITY_ORDER: SeverityKey[] = [
  "NORMAL",
  "WARNING",
  "CRITICAL",
  "INCIDENT",
];

/** Categorical slots, in the validated fixed order. Never cycled. */
export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];

/**
 * Conflict types get fixed slots so a colour follows the entity and never its
 * rank — filtering the list must not repaint the survivors.
 */
export const CONFLICT_TYPE_ORDER = [
  "REAR_END",
  "OVERTAKING",
  "LANE_CHANGE",
  "SIDE_BY_SIDE",
  "DEFENSIVE",
  "CROSSING",
  "MULTI_CAR_CHAIN",
] as const;

export const CONFLICT_TYPE_COLOR: Record<string, string> = Object.fromEntries(
  CONFLICT_TYPE_ORDER.map((t, i) => [t, SERIES[i % SERIES.length]])
);

export const CONFLICT_TYPE_LABEL: Record<string, string> = {
  REAR_END: "Rear-end",
  OVERTAKING: "Overtaking",
  LANE_CHANGE: "Lane change",
  SIDE_BY_SIDE: "Side by side",
  DEFENSIVE: "Defensive",
  CROSSING: "Crossing",
  MULTI_CAR_CHAIN: "Multi-car chain",
};

/** Weather is ordered, so it uses the single-hue ordinal ramp, brightest = worst. */
export const WEATHER_ORDER = ["DRY", "DAMP", "WET", "HEAVY_RAIN"] as const;

export const WEATHER_COLOR: Record<string, string> = {
  DRY: "var(--seq-2)",
  DAMP: "var(--seq-3)",
  WET: "var(--seq-4)",
  HEAVY_RAIN: "var(--seq-6)",
};

export const WEATHER_LABEL: Record<string, string> = {
  DRY: "Dry",
  DAMP: "Damp",
  WET: "Wet",
  HEAVY_RAIN: "Heavy rain",
};

export const TRAFFIC_BAND_LABEL: Record<string, string> = {
  LOW: "Low traffic",
  MEDIUM: "Medium traffic",
  HIGH: "High traffic",
};

/** Sequential ramp stops, ordered near-zero → maximum on a dark surface. */
export const SEQ_STOPS = [
  "#0d1a2c",
  "#0d366b",
  "#184f95",
  "#256abf",
  "#3987e5",
  "#5598e7",
  "#86b6ef",
  "#b7d3f6",
];

/** Interpolate the sequential ramp for a normalised value in [0, 1]. */
export function seqColor(t: number): string {
  if (!Number.isFinite(t)) return SEQ_STOPS[0];
  const x = Math.max(0, Math.min(1, t)) * (SEQ_STOPS.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  const a = SEQ_STOPS[i];
  const b = SEQ_STOPS[Math.min(i + 1, SEQ_STOPS.length - 1)];
  return mix(a, b, f);
}

function mix(a: string, b: string, t: number): string {
  const pa = hexToRgb(a);
  const pb = hexToRgb(b);
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r},${g},${bl})`;
}

function hexToRgb(h: string): [number, number, number] {
  const s = h.replace("#", "");
  return [
    parseInt(s.slice(0, 2), 16),
    parseInt(s.slice(2, 4), 16),
    parseInt(s.slice(4, 6), 16),
  ];
}

export const EVENT_TYPE_LABEL: Record<string, string> = {
  conflict: "Conflict",
  near_miss: "Near miss",
  collision: "Collision",
  light_contact: "Light contact",
  off_track: "Off track",
  spin: "Spin",
  hard_braking: "Hard braking",
  emergency_braking: "Emergency braking",
  evasive_manoeuvre: "Evasive manoeuvre",
  overtake_attempt: "Overtake attempt",
  overtake_complete: "Overtake complete",
  overtake_aborted: "Overtake aborted",
  defensive_move: "Defensive move",
  driver_error: "Driver error",
};

export const DECISION_LABEL: Record<string, string> = {
  accelerate: "Accelerate",
  brake: "Brake",
  coast: "Coast",
  maintain_line: "Hold line",
  move_left: "Move left",
  move_right: "Move right",
  initiate_overtake: "Overtaking",
  defend_inside: "Defend inside",
  defend_outside: "Defend outside",
  yield: "Yield",
  abort_overtake: "Abort overtake",
  avoid_collision: "Avoid collision",
  return_to_racing_line: "Return to line",
};

export const ARCHETYPE_SHORT: Record<string, string> = {
  AGGRESSIVE_OVERTAKER: "Aggressive",
  DEFENSIVE_SPECIALIST: "Defensive",
  CONSERVATIVE: "Conservative",
  LATE_BRAKER: "Late braker",
  HIGH_CONSISTENCY: "Consistent",
  OPPORTUNISTIC: "Opportunistic",
  HIGH_RISK: "High risk",
  SMOOTH: "Smooth",
  UNPREDICTABLE: "Unpredictable",
};

export const ERROR_LABEL: Record<string, string> = {
  missed_braking_point: "Missed braking point",
  delayed_reaction: "Delayed reaction",
  unexpected_line_change: "Unexpected line change",
  grip_loss: "Grip loss",
  concentration_lapse: "Concentration lapse",
  over_aggressive_overtake: "Over-aggressive overtake",
  incorrect_defensive_response: "Incorrect defensive response",
  spin: "Spin",
  slow_response_to_car_ahead: "Slow response to car ahead",
};
