"use client";

/**
 * Shared pieces for the Apex Passport screens: the selected-car state, the car
 * picker, part-life meters, status badges and the driver/spec editors.
 */

import { Car as CarIcon, Plus } from "lucide-react";
import Link from "next/link";
import React from "react";

import { Archetype } from "../lib/api";
import { dec } from "../lib/format";
import {
  Car,
  CarProfile,
  CLASS_LABEL,
  CONDITION_STATUS,
  ConditionStatus,
  DriverTrait,
  Part,
  PART_STATUS,
  partLabel,
  PartStatus,
  passportApi,
  TeamDriver,
} from "../lib/passport";
import { useApp, useFetch } from "../lib/store";
import { Badge, Button, EmptyState, ErrorState, Loading, Select, Slider } from "./ui";

/* ------------------------------------------------------- selected car --- */

const LS_CAR = "apex.passport.carId";

/**
 * The car every passport screen is about. Remembered per browser so moving
 * between screens keeps the same car; falls back to the most recent car.
 */
export function useSelectedCar() {
  const cars = useFetch(() => passportApi.cars(), []);
  const [stored, setStored] = React.useState<string | null>(() => {
    try {
      return typeof window === "undefined" ? null : localStorage.getItem(LS_CAR);
    } catch {
      return null; /* private browsing */
    }
  });

  const list = cars.data?.cars ?? [];
  const car = list.find((c) => c.id === stored) ?? list[0] ?? null;

  const select = React.useCallback((id: string) => {
    setStored(id);
    try {
      localStorage.setItem(LS_CAR, id);
    } catch {
      /* ignore */
    }
  }, []);

  return {
    cars: list,
    car,
    select,
    loading: cars.loading && !cars.data,
    error: cars.error,
    reload: cars.reload,
  };
}

/** Wraps a passport screen: shows loading/error/empty states, then a car picker. */
export function RequireCar({
  children,
}: {
  children: (car: Car, reloadCars: () => void) => React.ReactNode;
}) {
  const { cars, car, select, loading, error, reload } = useSelectedCar();
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading) return <Loading label="Loading cars" />;
  if (!car) {
    return (
      <EmptyState
        title="No car in the garage yet"
        body="A passport belongs to one car. Set one up — its spec, parts and team driver — and every passport screen will follow it."
        action={
          <Link href="/passport">
            <Button variant="primary">
              <Plus size={12} /> Set up a car
            </Button>
          </Link>
        }
      />
    );
  }
  return (
    <>
      <CarPicker cars={cars} car={car} onSelect={select} />
      {children(car, reload)}
    </>
  );
}

export function CarPicker({
  cars,
  car,
  onSelect,
}: {
  cars: Car[];
  car: Car;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-end gap-3 rounded-md border border-line bg-surface-1/90 px-3.5 py-2.5">
      <CarIcon size={14} className="mb-1.5 text-ink-3" aria-hidden />
      <Select
        label="Car"
        value={car.id}
        onChange={onSelect}
        className="w-[260px]"
        options={cars.map((c) => ({
          value: c.id,
          label: `${c.name} · ${CLASS_LABEL[c.class] ?? c.class}`,
        }))}
      />
      <span className="mb-1.5 text-[11px] text-ink-3">
        Driver: <span className="text-ink-2">{driverSummary(car.team_driver)}</span>
      </span>
      <span className="num mb-1.5 ml-auto text-[10.5px] text-ink-3">{car.id}</span>
    </div>
  );
}

export function driverSummary(d: TeamDriver, archetypes?: Archetype[]): string {
  const label =
    archetypes?.find((a) => a.id === d.archetype)?.label ??
    d.archetype.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
  const n = Object.keys(d.overrides ?? {}).length;
  return n ? `${label} (${n} trait${n === 1 ? "" : "s"} adjusted)` : label;
}

/* ------------------------------------------------------------- badges --- */

export function PartStatusBadge({ status }: { status: PartStatus }) {
  const s = PART_STATUS[status];
  return (
    <Badge color={s.color} glyph={s.glyph}>
      {s.label}
    </Badge>
  );
}

export function ConditionBadge({ status }: { status: ConditionStatus }) {
  const s = CONDITION_STATUS[status];
  return (
    <Badge color={s.color} glyph={s.glyph}>
      {s.label}
    </Badge>
  );
}

/* ------------------------------------------------------- part meters --- */

/**
 * Life used, 0–100%. A meter, not a chart: one value per part against fixed
 * amber/red thresholds, which are drawn as ticks so the colour is never the
 * only cue.
 */
export function LifeMeter({
  value,
  status,
  amber = 70,
  red = 90,
}: {
  value: number;
  status: PartStatus;
  amber?: number;
  red?: number;
}) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div
      className="relative h-[8px] w-full rounded-full bg-surface-3"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={v}
      title={`${dec(value, 1)}% life used`}
    >
      <div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ width: `${v}%`, background: PART_STATUS[status].color }}
      />
      {[amber, red].map((t) => (
        <span
          key={t}
          className="absolute -inset-y-[2px] w-[1px] bg-[color:var(--text-muted)]"
          style={{ left: `${t}%` }}
          aria-hidden
        />
      ))}
    </div>
  );
}

export function PartRow({ part, action }: { part: Part; action?: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(150px,1.2fr)_2fr_64px_auto] items-center gap-3 border-b border-line/60 py-2 last:border-0">
      <span className="truncate text-[12px] text-ink-2">{partLabel(part.name)}</span>
      <LifeMeter value={part.life_used_pct} status={part.status} />
      <span className="num text-right text-[12px] text-ink">
        {dec(part.life_used_pct, 1)}%
      </span>
      <span className="flex items-center justify-end gap-2">
        <PartStatusBadge status={part.status} />
        {action}
      </span>
    </div>
  );
}

/* ----------------------------------------------------- driver editor --- */

export function DriverEditor({
  value,
  onChange,
  archetypes,
  traits,
}: {
  value: TeamDriver;
  onChange: (d: TeamDriver) => void;
  archetypes: Archetype[];
  traits: DriverTrait[];
}) {
  const base = archetypes.find((a) => a.id === value.archetype);
  const traitValue = (key: string): number =>
    value.overrides[key] ?? Number((base as unknown as Record<string, number>)?.[key] ?? 0);

  const setTrait = (key: string, v: number) => {
    const baseV = Number((base as unknown as Record<string, number>)?.[key]);
    const overrides = { ...value.overrides };
    // Moving a slider back onto the archetype's own value removes the override,
    // so "adjusted" always means actually different from the archetype.
    if (Math.abs(v - baseV) < 1e-9) delete overrides[key];
    else overrides[key] = v;
    onChange({ ...value, overrides });
  };

  const fmt = (t: DriverTrait) => (v: number) =>
    t.unit === "s" ? `${v.toFixed(3)} s` : t.unit === "×" ? `${v.toFixed(3)}×` : v.toFixed(2);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label="Starting archetype"
          value={value.archetype}
          onChange={(a) => onChange({ archetype: a, overrides: {} })}
          className="w-[240px]"
          options={archetypes.map((a) => ({ value: a.id, label: a.label }))}
        />
        {Object.keys(value.overrides).length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => onChange({ ...value, overrides: {} })}>
            Reset to archetype
          </Button>
        )}
      </div>
      {base && <p className="text-[11.5px] leading-relaxed text-ink-3">{base.note}</p>}
      <div className="grid gap-x-5 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
        {traits.map((t) => {
          const adjusted = t.key in value.overrides;
          return (
            <div key={t.key} className="relative">
              <Slider
                label={adjusted ? `${t.label} •` : t.label}
                value={traitValue(t.key)}
                min={t.min}
                max={t.max}
                step={t.step}
                onChange={(v) => setTrait(t.key, v)}
                format={fmt(t)}
                hint={t.note}
              />
            </div>
          );
        })}
      </div>
      <p className="text-[10.5px] text-ink-3">
        • marks a trait changed from the archetype. Values are clamped by the engine to
        the ranges shown.
      </p>
    </div>
  );
}

/* ------------------------------------------------------- spec editor --- */

const SPEC_FIELDS: { key: keyof CarProfile; label: string; unit: string; step: number }[] = [
  { key: "mass_kg", label: "Mass (with driver)", unit: "kg", step: 5 },
  { key: "power_kw", label: "Power", unit: "kW", step: 5 },
  { key: "battery_power_kw", label: "Battery power", unit: "kW", step: 5 },
  { key: "top_speed_kmh", label: "Top speed", unit: "km/h", step: 5 },
  { key: "tyre_grip_coeff", label: "Tyre grip", unit: "μ", step: 0.01 },
  { key: "downforce_coeff", label: "Downforce", unit: "coef", step: 0.05 },
  { key: "drag_coeff", label: "Drag", unit: "coef", step: 0.05 },
  { key: "max_brake_g", label: "Max braking", unit: "g", step: 0.05 },
  { key: "front_weight_pct", label: "Front weight", unit: "%", step: 0.5 },
  { key: "aero_balance_front_pct", label: "Aero balance (front)", unit: "%", step: 0.5 },
  { key: "cg_height_m", label: "CG height", unit: "m", step: 0.01 },
];

export function SpecEditor({
  value,
  onChange,
}: {
  value: CarProfile;
  onChange: (p: CarProfile) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {SPEC_FIELDS.map((f) => {
        const v = value[f.key] as number | null;
        return (
          <label key={f.key} className="flex flex-col gap-1">
            <span className="label-xs">{f.label}</span>
            <span className="flex items-center rounded border border-line-strong bg-surface-2 focus-within:border-[color:var(--accent)]">
              <input
                type="number"
                step={f.step}
                value={v ?? ""}
                placeholder={f.key === "battery_power_kw" ? "none" : undefined}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [f.key]: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                className="num w-full min-w-0 bg-transparent px-2 py-1.5 text-[12px] text-ink outline-none"
              />
              <span className="shrink-0 pr-2 text-[10.5px] text-ink-3">{f.unit}</span>
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** App metadata the passport editors need: archetypes (from /api/meta) and trait bounds. */
export function usePassportCatalogue() {
  const { meta } = useApp();
  const presets = useFetch(() => passportApi.presets(), []);
  return {
    archetypes: meta?.archetypes ?? [],
    presets: presets.data?.presets ?? [],
    traits: presets.data?.driver_traits ?? [],
    error: presets.error,
    loading: !presets.data && !presets.error,
  };
}
