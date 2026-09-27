/**
 * Apex Passport API client.
 *
 * Kept separate from api.ts so the passport feature stays additive. Every
 * payload carries a `note` or `disclaimer` from the backend; screens render
 * those strings rather than writing their own framing.
 */

import { get, JobSnapshot, post, put } from "./api";

/* ---------------------------------------------------------------- types --- */

export interface CarProfile {
  mass_kg: number;
  front_weight_pct: number;
  cg_height_m: number;
  power_kw: number;
  top_speed_kmh: number;
  tyre_grip_coeff: number;
  downforce_coeff: number;
  drag_coeff: number;
  aero_balance_front_pct: number;
  max_brake_g: number;
  battery_power_kw: number | null;
  class_name: string;
}

export type CarPreset = CarProfile & { id: string };

export interface DriverTrait {
  key: string;
  label: string;
  min: number;
  max: number;
  step: number;
  unit: string;
  note: string;
}

export interface TeamDriver {
  archetype: string;
  overrides: Record<string, number>;
}

export interface Car {
  id: string;
  name: string;
  class: string;
  car_profile: CarProfile;
  team_driver: TeamDriver;
  created_at: string;
}

export type PartStatus = "green" | "amber" | "red";

export interface Part {
  car_id: string;
  name: string;
  life_used_pct: number;
  part_cost: number;
  status: PartStatus;
  updated_at: string;
}

export interface HistoryEvent {
  id: number;
  car_id: string;
  time: string;
  type: string;
  details: Record<string, unknown>;
  hash: string;
  prev_hash: string;
  seq: number;
}

export interface ChainVerification {
  valid: boolean;
  checked: number;
  broken_event_id: number | null;
  reason: string | null;
}

export type ConditionStatus = "met" | "at_risk" | "breached";

export interface PolicyCondition {
  key: string;
  label: string;
  status: ConditionStatus;
  detail: string;
}

export interface PassportView {
  car: Car;
  parts: Part[];
  history: HistoryEvent[];
  chain_verification: ChainVerification;
  policy_conditions: PolicyCondition[];
  note: string;
}

export interface StressPartReport {
  part: string;
  current_life_used_pct: number;
  predicted_median_pct: number;
  predicted_min_pct: number;
  predicted_max_pct: number;
  races_crossing_red: number;
  races_evaluated: number;
  status: PartStatus;
}

export interface CloseCall {
  run_id: string;
  min_ttc: number;
  min_pet: number | null;
  n_collisions: number;
  n_light_contacts: number;
  has_replay: boolean;
}

export interface StressTestResult {
  batch_id: string;
  car_id: string;
  car_name: string;
  track_id: string;
  weather: string;
  n_races: number;
  driver?: TeamDriver;
  created_at?: string;
  parts: StressPartReport[];
  parts_crossing_red_count: number;
  close_calls: CloseCall[];
  n_close_calls: number;
  cost_forecast: {
    expected_wear_replacement_cost: number;
    expected_repair_cost_per_race: number;
    total: number;
  };
  recommendations: string[];
  note: string;
}

export interface Incident {
  id: string;
  car_id: string;
  reported_at: string;
  occurred_at: string;
  description: string;
  affected_parts: string[];
  before_snapshot: Part[];
  history_event_id: number;
}

export interface ClaimPack {
  car: Car;
  incident: Incident;
  comparison: {
    part: string;
    life_used_pct_before: number | null;
    life_used_pct_after: number;
    status_before: PartStatus | null;
    status_after: PartStatus;
    changed: boolean;
  }[];
  chain_verification: ChainVerification;
  disclaimer: string;
  generated_at: string;
}

export interface InsurerSummary {
  car: Car;
  parts: Part[];
  policy_conditions: PolicyCondition[];
  chain_verification: ChainVerification;
  incident_count: number;
  contact_event_count: number;
  history_event_count: number;
  latest_stress_test: StressTestResult | null;
  plain_english_summary: string;
  generated_at: string;
  disclaimer: string;
}

export type StressJob = JobSnapshot & { result?: StressTestResult | null };

/* --------------------------------------------------------------- client --- */

export const passportApi = {
  presets: () =>
    get<{ presets: CarPreset[]; classes: string[]; driver_traits: DriverTrait[] }>(
      "/api/car-presets"
    ),
  cars: () => get<{ cars: Car[]; note: string }>("/api/cars"),
  createCar: (body: {
    name: string;
    car_class: string;
    car_profile?: Partial<CarProfile>;
    team_driver?: TeamDriver;
  }) => post<Car>("/api/cars", body),
  setDriver: (carId: string, driver: TeamDriver) =>
    put<Car>(`/api/cars/${carId}/driver`, driver),
  passport: (carId: string) => get<PassportView>(`/api/cars/${carId}/passport`),
  replacePart: (carId: string, part: string) =>
    post<{ event: HistoryEvent; parts: Part[] }>(
      `/api/cars/${carId}/parts/${part}/replace`
    ),
  verify: (carId: string) => get<ChainVerification>(`/api/cars/${carId}/verify`),

  startStressTest: (
    carId: string,
    body: { track_id?: string; weather?: string; n_races?: number }
  ) => post<StressJob>(`/api/cars/${carId}/stress-test`, body),
  stressJob: (jobId: string) => get<StressJob>(`/api/stress-test/${jobId}`),
  latestStressTest: (carId: string) =>
    get<{ result: StressTestResult | null }>(`/api/cars/${carId}/stress-tests/latest`),

  incidents: (carId: string) =>
    get<{ incidents: Incident[] }>(`/api/cars/${carId}/incidents`),
  logIncident: (
    carId: string,
    body: { description: string; occurred_at?: string; affected_parts?: string[] }
  ) =>
    post<{ incident_id: string; history_event_id: number; before_snapshot: Part[] }>(
      `/api/cars/${carId}/incidents`,
      body
    ),
  claimPack: (carId: string, incidentId: string) =>
    get<ClaimPack>(`/api/cars/${carId}/claim-pack/${incidentId}`),
  insurerSummary: (carId: string) =>
    get<InsurerSummary>(`/api/cars/${carId}/insurer-summary`),
};

/* ------------------------------------------------------------ vocabulary --- */

export const PART_LABEL: Record<string, string> = {
  suspension_fl: "Suspension · front left",
  suspension_fr: "Suspension · front right",
  suspension_rl: "Suspension · rear left",
  suspension_rr: "Suspension · rear right",
};

export const partLabel = (name: string): string =>
  PART_LABEL[name] ?? name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Part status shares the app's status ramp and always carries a glyph. */
export const PART_STATUS: Record<PartStatus, { label: string; color: string; glyph: string }> = {
  green: { label: "Good", color: "var(--good)", glyph: "●" },
  amber: { label: "Inspect", color: "var(--warning)", glyph: "▲" },
  red: { label: "Replace", color: "var(--critical)", glyph: "✕" },
};

export const CONDITION_STATUS: Record<
  ConditionStatus,
  { label: string; color: string; glyph: string }
> = {
  met: { label: "Met", color: "var(--good)", glyph: "●" },
  at_risk: { label: "At risk", color: "var(--warning)", glyph: "▲" },
  breached: { label: "Breached", color: "var(--critical)", glyph: "✕" },
};

export const EVENT_LABEL: Record<string, string> = {
  race: "Race",
  kerb_hit: "Kerb hit",
  contact: "Contact",
  part_replaced: "Part replaced",
  inspection: "Inspection",
  incident: "Incident",
  stress_test: "Stress test",
  driver_updated: "Driver updated",
};

export const CLASS_LABEL: Record<string, string> = {
  F1_2026: "F1 (2026)",
  F2: "Formula 2",
  F3: "Formula 3",
  F4: "Formula 4",
  FORMULA_E: "Formula E",
  FORMULA_STUDENT: "Formula Student",
  CUSTOM: "Custom",
};
