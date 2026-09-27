/**
 * API client.
 *
 * Every payload from the backend carries a `note`, `caveat` or `interpretation`
 * string stating what its numbers are. The UI renders those strings rather than
 * writing its own wording, so the distinction between a simulated conflict count
 * and a real-world risk cannot be lost in the presentation layer.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the simulation API at ${API_BASE}. Start it with: ` +
        `cd backend && ../.venv/bin/uvicorn apex.api:app --port 8000`,
      0
    );
  }
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => undefined);
    }
    const msg =
      (detail as { detail?: string })?.detail ??
      `${res.status} ${res.statusText}`;
    throw new ApiError(String(msg), res.status, detail);
  }
  return (await res.json()) as T;
}

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
export const put = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) });
export const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

export const getText = async (path: string): Promise<string> => {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new ApiError(`${res.status} ${res.statusText}`, res.status);
  return res.text();
};

/* ---------------------------------------------------------------- types --- */

export interface Meta {
  name: string;
  subtitle: string;
  disclaimer: string;
  positioning: string;
  tracks: TrackSummary[];
  archetypes: Archetype[];
  weathers: string[];
  experiments: ExperimentSpec[];
  intervention_presets: InterventionPreset[];
  query_suggestions: string[];
  default_space: Record<string, unknown>;
  thresholds: Record<string, number>;
}

export interface TrackSummary {
  id: string;
  name: string;
  country: string;
  length: number;
  n_segments: number;
  n_corners: number;
  closure_error: number;
  min_width: number;
  max_width: number;
}

export interface Archetype {
  id: string;
  label: string;
  note: string;
  aggression: number;
  risk_tolerance: number;
  overtake_willingness: number;
  defensive_tendency: number;
  reaction_time: number;
  braking_consistency: number;
  late_braking_tendency: number;
  line_change_tendency: number;
  error_probability: number;
  predictability: number;
  pace_multiplier: number;
  perturbation_scale: Record<string, number>;
}

export interface ExperimentSpec {
  key: string;
  number: number;
  name: string;
  question: string;
  dimension: string;
  arms: string[];
}

export interface InterventionPreset {
  id: string;
  name: string;
  description: string;
  changes: Record<string, number | string>;
}

export interface Assumption {
  key: string;
  value: unknown;
  unit: string;
  kind: "methodology" | "assumption" | "derived";
  group: string;
  label: string;
  note: string;
  reference: string;
  tunable: boolean;
  range: [number, number] | null;
}

export interface AssumptionsPayload {
  groups: string[];
  assumptions: Assumption[];
  counts: { total: number; methodology: number; assumption: number };
  provenance_note: string;
  scsi: {
    weights: Record<string, number>;
    closing_speed_ref: number;
    decel_ref: number;
    definition: string;
  };
  references: { label: string; url: string }[];
}

export interface TrackSegment {
  index: number;
  name: string;
  type: string;
  turn_number: number | null;
  length: number;
  width: number;
  curvature: number;
  corner_radius: number | null;
  target_speed: number;
  target_speed_kph: number;
  is_braking_zone: boolean;
  overtaking_opportunity: number;
  runoff_width: number;
  barrier_distance: number;
  s_start: number;
  s_end: number;
  s_mid: number;
}

export interface TrackGeometry {
  id: string;
  name: string;
  country: string;
  length: number;
  closure_error: number;
  centreline: { x: number[]; y: number[]; s: number[]; heading: number[]; width: number[] };
  edges: { left: { x: number[]; y: number[] }; right: { x: number[]; y: number[] } };
  racing_line: { s: number[]; d: number[] };
  segments: TrackSegment[];
  zones: Zone[];
  segment_to_zone: Record<string, number>;
}

export interface Zone {
  turn_number: number;
  key: string;
  name: string;
  corner_name: string;
  corner_segment_index: number;
  corner_radius: number;
  width: number;
  min_width: number;
  runoff_width: number;
  barrier_distance: number;
  target_speed: number;
  overtaking_opportunity: number;
  segment_indices: number[];
  s_start: number;
  s_end: number;
  length: number;
}

export interface BatchRow {
  id: string;
  created_at: string;
  label: string;
  mode: string;
  n_runs_requested: number;
  n_runs_completed: number;
  status: string;
  wall_time_ms: number | null;
  seed_base: number;
  conflicts: number | null;
  critical: number | null;
  collisions: number | null;
  near_misses: number | null;
  avg_min_ttc: number | null;
  lowest_min_ttc: number | null;
  avg_min_pet: number | null;
  avg_cars: number | null;
}

export interface Overview {
  batch_id: string;
  label: string;
  mode: string;
  status: string;
  created_at: string;
  n_runs_requested: number;
  n_runs_completed: number;
  seed_base: number;
  wall_time_ms: number | null;
  totals: Record<string, number | null>;
  min_ttc_distribution: {
    lo: number;
    hi: number | null;
    count: number;
    fraction: number;
    label: string;
  }[];
  runs_with_critical: number;
  runs_with_contact: number;
  fraction_runs_with_critical: number;
  summary: Record<string, unknown>;
  config: Record<string, unknown>;
  space: Record<string, unknown>;
  pin: Record<string, unknown>;
}

export interface HotspotSegment {
  segment_index: number;
  name: string;
  type: string;
  turn_number: number | null;
  s_start: number;
  s_end: number;
  length: number;
  width: number;
  corner_radius: number | null;
  target_speed_kph: number;
  runoff_width: number;
  barrier_distance: number;
  overtaking_opportunity: number;
  is_braking_zone: boolean;
  conflicts: number;
  conflicts_per_run: number;
  conflicts_per_100m_per_run: number;
  critical: number;
  incidents: number;
  warnings: number;
  collisions: number;
  evasive: number;
  median_min_ttc: number | null;
  p05_min_ttc: number | null;
  median_min_pet: number | null;
  median_closing_speed: number | null;
  mean_scsi: number | null;
  conflict_type_mix: Record<string, number>;
  weather_mix: Record<string, number>;
  dominant_errors: Record<string, number>;
  top_archetype_pairs: { pair: string[]; count: number }[];
  example_run_ids: string[];
}

export interface Hotspots {
  batch_id: string;
  track_id: string;
  n_runs: number;
  total_conflicts: number;
  segments: HotspotSegment[];
  ranked_segments: number[];
  top_segments: HotspotSegment[];
  top_corners: HotspotSegment[];
  note: string;
}

export interface HotspotDetail {
  segment_index: number;
  text: string;
  detail: {
    segment: HotspotSegment;
    n_runs: number;
    weather_contrast: { band: string; runs: number; conflicts: number; conflicts_per_run: number }[];
    density_contrast: { band: string; runs: number; conflicts: number; conflicts_per_run: number }[];
    worst_conflicts: ConflictRow[];
    geometry_note: string;
    note: string;
  };
}

export interface SensitivityParam {
  key: string;
  label: string;
  n: number;
  range: [number, number];
  correlations: Record<string, number>;
  bands: (Record<string, number | null> & { lo: number; hi: number; mid: number; runs: number })[];
}

export interface Sensitivity {
  batch_id: string;
  n_runs: number;
  parameters: SensitivityParam[];
  outcomes: { key: string; label: string }[];
  interactions: {
    label: string;
    a_key: string;
    b_key: string;
    a_edges: number[];
    b_edges: number[];
    cells: {
      i: number;
      j: number;
      a_lo: number;
      a_hi: number;
      b_lo: number;
      b_hi: number;
      runs: number;
      critical_per_run: number;
      conflicts_per_run: number;
      collisions_per_run: number;
    }[];
  }[];
  method_note: string;
}

export interface MatrixCell {
  a: string;
  b: string;
  i: number;
  j: number;
  co_present_runs: number;
  conflicts: number;
  critical: number;
  collisions: number;
  conflicts_per_co_present_run: number | null;
  critical_per_co_present_run: number | null;
  median_min_ttc: number | null;
  dominant_conflict_type: string | null;
  conflict_type_mix: Record<string, number>;
  weather_mix: Record<string, number>;
  sparse: boolean;
}

export interface InteractionMatrix {
  batch_id: string;
  archetypes: { id: string; label: string; note: string; present_in_runs: number }[];
  cells: MatrixCell[];
  n_runs: number;
  note: string;
}

export interface EnvironmentAnalysis {
  batch_id: string;
  by_weather: Record<string, number | string>[];
  conflict_types_by_weather: { weather: string; conflict_type: string; n: number; mean_ttc: number }[];
  top_locations_by_weather: Record<string, { location: string; turn_number: number | null; n: number }[]>;
  presets: Record<string, Record<string, number>>;
  note: string;
}

export interface ConflictBreakdown {
  batch_id: string;
  by_type_and_severity: Record<string, number | string>[];
  decision_pairs: { a_decision: string; b_decision: string; n: number; mean_ttc: number }[];
  by_dominant_error: Record<string, number | string | null>[];
}

export interface Pattern {
  id: string;
  batch_id: string;
  rank: number;
  pattern_key: string;
  track_id: string;
  segment_index: number;
  location: string;
  turn_number: number | null;
  weather: string;
  n_cars: number;
  traffic_band: string;
  archetype_a: string;
  archetype_b: string;
  conflict_type: string;
  dominant_error: string | null;
  occurrences: number;
  runs_evaluated: number;
  /** Runs drawn in this pattern's weather and traffic band. */
  band_runs: number | null;
  /** occurrences / band_runs — the conditional rate within comparable runs. */
  occurrence_rate: number | null;
  median_min_ttc: number;
  p05_min_ttc: number;
  median_min_pet: number | null;
  median_closing_speed: number;
  evasive_rate: number;
  collision_rate: number;
  mean_scsi: number;
  example_run_ids: string[];
  conditions: {
    zone: string;
    corner_name: string;
    corner_radius: number;
    zone_min_width: number;
    runoff_width: number;
    overtaking_opportunity: number;
    weather: string;
    traffic_band: string;
    conflict_instances: number;
    mean_traffic_density: number;
    mean_n_cars: number;
    mean_grip: number;
    mean_visibility: number;
    field_bands: Record<string, number>;
    dominant_archetype_pairs: { pair: string[]; count: number; share: number }[];
    dominant_errors: { error: string; count: number; share: number }[];
    decision_pairs: { decisions: string; count: number }[];
    segments_within_zone: { location: string; count: number }[];
    median_max_deceleration: number;
    median_max_deceleration_g: number;
  };
}

export interface RunRow {
  id: string;
  batch_id: string;
  created_at: string;
  seed: number;
  track_id: string;
  n_cars: number;
  weather: string;
  grip: number;
  visibility: number;
  spray: number;
  tyre_condition: number;
  track_temp: number;
  ambient_temp: number;
  wind: number;
  traffic_density_requested: number;
  traffic_density_measured: number;
  grid_spread: number;
  pace_spread: number;
  track_width_multiplier: number;
  error_rate_multiplier: number;
  overtake_threshold_delta: number;
  following_gap_delta: number;
  duration: number;
  n_timesteps: number;
  wall_time_ms: number;
  origin: string;
  generation: number;
  config_fingerprint: string;
  n_conflicts: number;
  n_warnings: number;
  n_critical: number;
  n_near_misses: number;
  n_collisions: number;
  n_light_contacts: number;
  n_off_track: number;
  n_spins: number;
  n_barrier_strikes: number;
  n_evasive: number;
  n_overtake_attempts: number;
  n_overtakes_completed: number;
  n_driver_errors: number;
  min_ttc: number | null;
  min_pet: number | null;
  max_closing_speed: number;
  max_deceleration: number;
  peak_scsi: number;
  hotspot_segment: number | null;
  dominant_error: string | null;
  laps_completed: number;
  has_replay: number;
  field_mix: string[];
  error_counts: Record<string, number>;
}

export interface ConflictRow {
  id?: number;
  run_id: string;
  batch_id: string;
  driver_a: string;
  driver_b: string;
  driver_a_index: number;
  driver_b_index: number;
  archetype_a: string;
  archetype_b: string;
  conflict_type: string;
  severity: string;
  t_min_ttc: number;
  timestep: number;
  segment_index: number;
  location: string;
  turn_number: number | null;
  min_ttc: number;
  min_pet: number | null;
  closing_speed: number;
  max_deceleration: number;
  evasive_action: number;
  collision: number;
  scsi: number;
  a_decision: string;
  b_decision: string;
  weather: string;
  traffic_density: number;
  n_cars: number;
  has_replay?: number;
  grip?: number;
  visibility?: number;
  dominant_error?: string | null;
}

export interface EventRow {
  id: number;
  run_id: string;
  t: number;
  timestep: number;
  event_type: string;
  severity: string;
  segment_index: number;
  location: string;
  driver_a: string;
  driver_b: string | null;
  driver_a_index: number | null;
  driver_b_index: number | null;
  min_ttc: number | null;
  min_pet: number | null;
  closing_speed: number | null;
  max_deceleration: number | null;
  lateral_rate: number | null;
  evasive_action: number;
  collision: number;
  off_track: number;
  detail: Record<string, unknown>;
}

export interface ReplayCar {
  driver_index: number;
  driver_id: string;
  name: string;
  archetype: string;
  is_focus: boolean;
  x: number[];
  y: number[];
  s: number[];
  d: number[];
  speed: number[];
  accel: number[];
  throttle: number[];
  brake: number[];
  lateral_rate: number[];
  segment: number[];
  decision: string[];
}

export interface Replay {
  run_id: string;
  track_id: string;
  dt: number;
  t_start: number;
  t_end: number;
  t_focus: number;
  n_frames: number;
  frame_times: number[];
  cars: ReplayCar[];
  ttc_trace: {
    t: number;
    ttc: number | null;
    gap: number;
    closing_speed: number;
    lateral_separation: number;
  }[];
  events: EventRow[];
  environment: Record<string, number | string>;
  error_log: { t: number; driver_index: number; kind: string }[];
  focus_timestep: number;
  focus_drivers: number[];
}

export interface ExplainPayload {
  run_id: string;
  conflict: ConflictRow | null;
  n_conflicts: number;
  root_conditions: {
    group: string;
    label: string;
    value: string | number;
    detail?: string;
    traits?: Record<string, number>;
  }[];
  event_chain: {
    t: number | null;
    kind: string;
    actor: string | null;
    text: string;
    metrics: Record<string, unknown> | null;
  }[];
  narrative: string;
  metrics: {
    min_ttc: number;
    min_pet: number | null;
    closing_speed: number;
    closing_speed_kph: number;
    max_deceleration: number;
    max_deceleration_g: number;
    evasive_action: boolean;
    collision: boolean;
    conflict_type: string;
    severity: string;
    scsi: number;
    scsi_breakdown: {
      terms: Record<string, number>;
      weights: Record<string, number>;
      contributions: Record<string, number>;
      total: number;
    };
    thresholds: Record<string, number>;
  };
  has_replay: boolean;
  caveat: string;
}

export interface JobSnapshot {
  job_id: string;
  kind: string;
  label: string;
  status: "running" | "complete" | "error";
  phase: string;
  completed: number;
  total: number;
  elapsed_s: number;
  batch_id: string | null;
  error: string | null;
  runs_per_second: number;
  latest: Record<string, number | string>;
  event?: Record<string, number | string>;
  result?: Record<string, unknown>;
}

export interface LivePayload {
  run_id: string;
  seed: number;
  track_id: string;
  dt: number;
  n_frames: number;
  duration: number;
  drivers: {
    index: number;
    id: string;
    name: string;
    archetype: string;
    aggression: number;
    risk_tolerance: number;
    overtake_willingness: number;
    defensive_tendency: number;
    reaction_time: number;
    late_braking_tendency: number;
    braking_consistency: number;
    predictability: number;
    pace_multiplier: number;
  }[];
  frames: {
    t: number;
    step: number;
    x: number[];
    y: number[];
    speed: number[];
    speed_kph: number[];
    brake: number[];
    throttle: number[];
    accel: number[];
    d: number[];
    s: number[];
    segment: number[];
    decision: string[];
  }[];
  order_frames: number[][];
  feed: (Record<string, unknown> & {
    t: number;
    stream_frame: number;
    event_type: string;
    severity: string;
    location: string;
  })[];
  environment: Record<string, number | string>;
  summary: Record<string, number | string | null | Record<string, number>>;
  conflicts: ConflictRow[];
  note: string;
}

export interface AskResponse {
  question: string;
  intent: string;
  intent_description: string;
  answer: string | null;
  error?: string;
  data?: Record<string, unknown>;
  queries?: { sql: string; params: unknown[] }[];
  suggestions: string[];
  provenance: string;
  note?: string;
}

export interface InterventionResult {
  id: string;
  baseline_batch_id: string;
  intervention_batch_id: string;
  changes: Record<string, number | string>;
  n_runs: number;
  n_pairs: number;
  seed_base: number;
  baseline: Record<string, { mean: number | null; median: number | null; sem: number | null } | number>;
  intervention: Record<string, { mean: number | null; median: number | null; sem: number | null } | number>;
  paired: Record<
    string,
    {
      label: string;
      n_pairs: number;
      mean_difference: number;
      sem: number;
      exceeds_noise: boolean | null;
      improved_pairs: number;
      worsened_pairs: number;
      unchanged_pairs: number;
    }
  >;
  outcomes: { key: string; label: string }[];
  headline: string;
  note: string;
}

export interface ExperimentResult {
  id: string;
  experiment: string;
  number: number;
  name: string;
  question: string;
  dimension: string;
  runs_per_arm: number;
  seed_base: number;
  arms: {
    label: string;
    batch_id: string;
    pin: Record<string, unknown>;
    archetypes: string[] | null;
    stats: Record<string, { mean: number | null; median: number | null; sem: number | null } | number>;
  }[];
  outcomes: { key: string; label: string }[];
  deltas: {
    label: string;
    baseline_label: string;
    metrics: Record<
      string,
      {
        label: string;
        baseline: number;
        value: number;
        absolute: number;
        relative: number | null;
        pooled_sem: number;
        exceeds_noise: boolean | null;
      }
    >;
  }[];
  note: string;
}

export interface ReportPayload {
  batch_id: string;
  markdown: string;
  sections: string[];
  generated_at: string;
  n_runs: number;
}

/* ------------------------------------------------------------- endpoints --- */

export const api = {
  health: () => get<{ status: string; db: string; workers: number; batches: number; runs: number }>("/api/health"),
  meta: () => get<Meta>("/api/meta"),
  assumptions: () => get<AssumptionsPayload>("/api/assumptions"),
  track: (id: string, widthMultiplier = 1) =>
    get<TrackGeometry>(`/api/track/${id}?width_multiplier=${widthMultiplier}`),
  drivers: (nCars = 22) =>
    get<{ roster: Record<string, unknown>[]; archetypes: Archetype[]; note: string }>(
      `/api/drivers?n_cars=${nCars}`
    ),
  batches: (limit = 50) => get<{ batches: BatchRow[]; note: string }>(`/api/batches?limit=${limit}`),
  latestBatch: () =>
    get<{ batch_id: string; label: string; mode: string; created_at: string; n_runs: number }>(
      "/api/batches/latest"
    ),
  deleteBatch: (id: string) => del<{ deleted: string }>(`/api/batches/${id}`),

  overview: (b: string) => get<Overview>(`/api/analysis/${b}/overview`),
  hotspots: (b: string) => get<Hotspots>(`/api/analysis/${b}/hotspots`),
  hotspotDetail: (b: string, seg: number) =>
    get<HotspotDetail>(`/api/analysis/${b}/hotspots/${seg}`),
  sensitivity: (b: string) => get<Sensitivity>(`/api/analysis/${b}/sensitivity`),
  interactions: (b: string) => get<InteractionMatrix>(`/api/analysis/${b}/interactions`),
  environment: (b: string) => get<EnvironmentAnalysis>(`/api/analysis/${b}/environment`),
  conflictBreakdown: (b: string) => get<ConflictBreakdown>(`/api/analysis/${b}/conflicts`),
  recompute: (b: string) => post<{ batch_id: string }>(`/api/analysis/${b}/recompute`),

  patterns: (b: string, limit = 20) =>
    get<{ batch_id: string; patterns: Pattern[]; interpretation: string }>(
      `/api/patterns/${b}?limit=${limit}`
    ),

  runs: (params: Record<string, string | number | boolean | undefined>) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) q.set(k, String(v));
    });
    return get<{ runs: RunRow[]; total: number; limit: number; offset: number; note: string }>(
      `/api/runs?${q.toString()}`
    );
  },
  run: (id: string) =>
    get<{ run: RunRow & { scenario: Record<string, unknown> }; conflicts: ConflictRow[]; events: EventRow[]; note: string }>(
      `/api/runs/${id}`
    ),
  replay: (id: string) => get<Replay>(`/api/runs/${id}/replay`),
  explain: (id: string) => get<ExplainPayload>(`/api/runs/${id}/explain`),

  conflicts: (params: Record<string, string | number | boolean | undefined>) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) q.set(k, String(v));
    });
    return get<{ conflicts: ConflictRow[]; total: number; note: string }>(
      `/api/conflicts?${q.toString()}`
    );
  },

  startBatch: (body: Record<string, unknown>) => post<JobSnapshot>("/api/batches", body),
  startGuided: (body: Record<string, unknown>) => post<JobSnapshot>("/api/search/guided", body),
  jobs: () => get<{ jobs: JobSnapshot[] }>("/api/jobs"),
  job: (id: string) => get<JobSnapshot>(`/api/jobs/${id}`),

  live: (body: Record<string, unknown>) => post<LivePayload>("/api/live/run", body),

  runExperiment: (body: Record<string, unknown>) => post<JobSnapshot>("/api/experiments", body),
  whatIf: (body: Record<string, unknown>) => post<JobSnapshot>("/api/whatif", body),
  storedExperiments: () =>
    get<{ experiments: { id: string; created_at: string; name: string; kind: string; config: Record<string, unknown>; batch_ids: string[] }[] }>(
      "/api/experiments/stored"
    ),
  storedExperiment: (id: string) =>
    get<{ id: string; name: string; kind: string; created_at: string; config: Record<string, unknown>; results: Record<string, unknown>; batch_ids: string[] }>(
      `/api/experiments/stored/${id}`
    ),
  compareSearch: (randomBatch: string, guidedBatch: string) =>
    get<Record<string, Record<string, number | string>>>(
      `/api/search/compare?random_batch_id=${randomBatch}&guided_batch_id=${guidedBatch}`
    ),

  ask: (batchId: string, question: string) =>
    post<AskResponse>("/api/ask", { batch_id: batchId, question }),

  report: (b: string) => get<ReportPayload>(`/api/report/${b}`),
  reportMarkdown: (b: string) => getText(`/api/report/${b}/markdown`),
};

/** Subscribe to a job's SSE progress stream. Returns an unsubscribe function. */
export function streamJob(
  jobId: string,
  onUpdate: (snap: JobSnapshot) => void,
  onDone?: (snap: JobSnapshot) => void
): () => void {
  const es = new EventSource(`${API_BASE}/api/jobs/${jobId}/stream`);
  es.onmessage = (ev) => {
    try {
      const snap = JSON.parse(ev.data) as JobSnapshot;
      onUpdate(snap);
      if (snap.status !== "running") {
        onDone?.(snap);
        es.close();
      }
    } catch {
      /* keep-alive comments and partial frames are ignored */
    }
  };
  es.onerror = () => es.close();
  return () => es.close();
}
