"use client";

import { Check, Loader2, Plus, Save } from "lucide-react";
import Link from "next/link";
import React from "react";

import { PageHeader } from "../../components/Common";
import {
  DriverEditor,
  driverSummary,
  SpecEditor,
  usePassportCatalogue,
  useSelectedCar,
} from "../../components/passport";
import { Button, Caveat, ErrorState, Loading, Panel, Select } from "../../components/ui";
import { dec, kph } from "../../lib/format";
import {
  Car,
  CarProfile,
  CLASS_LABEL,
  passportApi,
  TeamDriver,
} from "../../lib/passport";

const DEFAULT_DRIVER: TeamDriver = { archetype: "HIGH_CONSISTENCY", overrides: {} };

export default function GaragePage() {
  const { cars, car, select, loading, error, reload } = useSelectedCar();
  const [creating, setCreating] = React.useState(false);

  return (
    <>
      <PageHeader
        title="Garage"
        lede="Each car has its own passport: its spec, its parts' condition, its team driver and a tamper-evident history. Set a car up here; the other passport screens follow the selected car."
        right={
          <Button variant="primary" onClick={() => setCreating((v) => !v)}>
            <Plus size={12} /> {creating ? "Close" : "New car"}
          </Button>
        }
      />

      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      {creating && (
        <NewCarForm
          onCreated={(c) => {
            select(c.id);
            reload();
            setCreating(false);
          }}
        />
      )}

      {loading ? (
        <Loading label="Loading cars" />
      ) : cars.length === 0 && !creating ? (
        <Panel>
          <p className="py-6 text-center text-[12px] text-ink-3">
            No cars yet. Use <span className="text-ink-2">New car</span> to set one up.
          </p>
        </Panel>
      ) : (
        <div className="grid gap-3">
          <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
            {cars.map((c) => (
              <CarCard key={c.id} car={c} selected={c.id === car?.id} onSelect={() => select(c.id)} />
            ))}
          </div>
          {car && <CarSetup key={car.id} car={car} onSaved={reload} />}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------ car card --- */

function CarCard({ car, selected, onSelect }: { car: Car; selected: boolean; onSelect: () => void }) {
  const { archetypes } = usePassportCatalogue();
  const p = car.car_profile;
  return (
    <button
      onClick={onSelect}
      aria-pressed={selected}
      className={`rounded-md border px-3.5 py-3 text-left transition-colors ${
        selected
          ? "border-[color:var(--accent)] bg-surface-2"
          : "border-line bg-surface-1/90 hover:bg-surface-2"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[13.5px] font-semibold text-ink">{car.name}</span>
        <span className="label-xs shrink-0">{CLASS_LABEL[car.class] ?? car.class}</span>
      </div>
      <p className="num mt-1.5 text-[11px] text-ink-3">
        {dec(p.mass_kg, 0)} kg · {dec(p.power_kw, 0)} kW · {kph(p.top_speed_kmh / 3.6)} ·{" "}
        {dec(p.max_brake_g, 2)} g
      </p>
      <p className="mt-1 truncate text-[11px] text-ink-3">
        Driver: <span className="text-ink-2">{driverSummary(car.team_driver, archetypes)}</span>
      </p>
    </button>
  );
}

/* ------------------------------------------------------- new car form --- */

function NewCarForm({ onCreated }: { onCreated: (c: Car) => void }) {
  const { archetypes, presets, traits, error: catErr } = usePassportCatalogue();
  const [name, setName] = React.useState("");
  const [cls, setCls] = React.useState("F3");
  // Spec edits belong to the class they were made on; switching class starts
  // again from that class's preset.
  const [edits, setEdits] = React.useState<{ cls: string; profile: CarProfile } | null>(null);
  const [driver, setDriver] = React.useState<TeamDriver>(DEFAULT_DRIVER);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);

  const preset = presets.find((x) => x.id === cls);
  const profile: CarProfile | null =
    edits?.cls === cls ? edits.profile : preset ? withoutId(preset) : null;
  const setProfile = (p: CarProfile) => setEdits({ cls, profile: p });

  const create = async () => {
    if (!name.trim() || !profile) return;
    setBusy(true);
    setErr(null);
    try {
      const car = await passportApi.createCar({
        name: name.trim(),
        car_class: cls,
        car_profile: profile,
        team_driver: driver,
      });
      onCreated(car);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="New car"
      subtitle="Start from a class preset, then adjust the spec and choose who drives it."
      className="mb-3"
    >
      {catErr || err ? <ErrorState error={catErr ?? err} /> : null}
      <div className="grid gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex w-[260px] flex-col gap-1">
            <span className="label-xs">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Car #7"
              className="rounded border border-line-strong bg-surface-2 px-2 py-1.5 text-[12px] text-ink outline-none focus:border-[color:var(--accent)]"
            />
          </label>
          <Select
            label="Class preset"
            value={cls}
            onChange={setCls}
            className="w-[200px]"
            options={presets.map((p) => ({ value: p.id, label: CLASS_LABEL[p.id] ?? p.id }))}
          />
        </div>

        <section>
          <h3 className="label-xs mb-2">Specification</h3>
          {profile ? <SpecEditor value={profile} onChange={setProfile} /> : <Loading />}
        </section>

        <section>
          <h3 className="label-xs mb-2">Team driver</h3>
          <DriverEditor value={driver} onChange={setDriver} archetypes={archetypes} traits={traits} />
        </section>

        <div className="flex items-center gap-3">
          <Button variant="primary" onClick={create} disabled={busy || !name.trim() || !profile}>
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
            Create car
          </Button>
          <Caveat>
            Class presets are illustrative figures, not manufacturer data.
          </Caveat>
        </div>
      </div>
    </Panel>
  );
}

function withoutId({ id: _id, ...spec }: CarProfile & { id: string }): CarProfile {
  void _id;
  return spec;
}

/* ------------------------------------------------------- car setup --- */

function CarSetup({ car, onSaved }: { car: Car; onSaved: () => void }) {
  const { archetypes, traits } = usePassportCatalogue();
  const [driver, setDriver] = React.useState<TeamDriver>(car.team_driver);
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);

  const dirty = JSON.stringify(driver) !== JSON.stringify(car.team_driver);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await passportApi.setDriver(car.id, driver);
      setSaved(true);
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const p = car.car_profile;

  return (
    <div className="grid gap-3 xl:grid-cols-[1fr_2fr]">
      <Panel
        title={`${car.name} · specification`}
        note="The spec is fixed once a car is created, so every stress test and history event refers to the same car. To test a different spec, create another car."
      >
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          {[
            ["Class", CLASS_LABEL[car.class] ?? car.class],
            ["Mass", `${dec(p.mass_kg, 0)} kg`],
            ["Power", `${dec(p.power_kw, 0)} kW`],
            ["Battery", p.battery_power_kw ? `${dec(p.battery_power_kw, 0)} kW` : "—"],
            ["Top speed", `${dec(p.top_speed_kmh, 0)} km/h`],
            ["Tyre grip", dec(p.tyre_grip_coeff, 2)],
            ["Downforce", dec(p.downforce_coeff, 2)],
            ["Drag", dec(p.drag_coeff, 2)],
            ["Max braking", `${dec(p.max_brake_g, 2)} g`],
            ["Front weight", `${dec(p.front_weight_pct, 1)}%`],
            ["Aero balance", `${dec(p.aero_balance_front_pct, 1)}% front`],
            ["CG height", `${dec(p.cg_height_m, 2)} m`],
          ].map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="label-xs">{k}</dt>
              <dd className="num mt-0.5 truncate text-[12.5px] text-ink">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link href="/passport/car">
            <Button size="sm">Open passport</Button>
          </Link>
          <Link href="/passport/stress-test">
            <Button size="sm">Stress test</Button>
          </Link>
        </div>
      </Panel>

      <Panel
        title="Team driver"
        subtitle="Who drives this car in its stress tests. Saving logs the change to the car's history, so each test's driver assumptions stay auditable."
        right={
          <Button variant="primary" size="sm" onClick={save} disabled={!dirty || busy}>
            {busy ? (
              <Loader2 size={11} className="animate-spin" />
            ) : saved && !dirty ? (
              <Check size={11} />
            ) : (
              <Save size={11} />
            )}
            {saved && !dirty ? "Saved" : "Save driver"}
          </Button>
        }
      >
        {err ? <ErrorState error={err} /> : null}
        <DriverEditor
          value={driver}
          onChange={(d) => {
            setDriver(d);
            setSaved(false);
          }}
          archetypes={archetypes}
          traits={traits}
        />
      </Panel>
    </div>
  );
}
