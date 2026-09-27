"use client";

import { Loader2, Pause, Play, RotateCcw, Zap } from "lucide-react";
import { useRouter } from "next/navigation";
import React from "react";

import { LineChart } from "../../components/charts";
import { CircuitMap, MapCar } from "../../components/CircuitMap";
import { Metric, PageHeader, SeverityLegend } from "../../components/Common";
import {
  Badge,
  Button,
  Caveat,
  ErrorState,
  Panel,
  SegmentedControl,
  Select,
  Skeleton,
  Slider,
  StatTile,
} from "../../components/ui";
import { api, LivePayload } from "../../lib/api";
import { clock, dec, int, sec } from "../../lib/format";
import { useApp } from "../../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_LABEL,
  DECISION_LABEL,
  EVENT_TYPE_LABEL,
  SEVERITY,
  SeverityKey,
  WEATHER_LABEL,
  WEATHER_ORDER,
} from "../../lib/theme";

const SPEEDS = [
  { value: "0.5", label: "0.5×" },
  { value: "1", label: "1×" },
  { value: "2", label: "2×" },
  { value: "4", label: "4×" },
  { value: "8", label: "8×" },
];

export default function LivePage() {
  const { track, apiOnline } = useApp();
  const router = useRouter();

  const [seed, setSeed] = React.useState(483921);
  const [weather, setWeather] = React.useState("WET");
  const [nCars, setNCars] = React.useState(22);
  const [density, setDensity] = React.useState(0.7);
  const [duration, setDuration] = React.useState(75);
  const [errMult, setErrMult] = React.useState(1.0);
  const [widthMult, setWidthMult] = React.useState(1.0);

  const [payload, setPayload] = React.useState<LivePayload | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  const [frame, setFrame] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState("2");
  const [focus, setFocus] = React.useState<number | null>(null);
  const raf = React.useRef<number | null>(null);
  const last = React.useRef(0);

  const run = async () => {
    setBusy(true);
    setError(null);
    setPlaying(false);
    try {
      const p = await api.live({
        seed,
        weather,
        n_cars: nCars,
        traffic_density: density,
        duration,
        error_rate_multiplier: errMult,
        track_width_multiplier: widthMult,
      });
      setPayload(p);
      setFrame(0);
      setFocus(null);
      setPlaying(true);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const nFrames = payload?.n_frames ?? 0;

  React.useEffect(() => {
    if (!playing || !payload) {
      if (raf.current) cancelAnimationFrame(raf.current);
      return;
    }
    const tick = (now: number) => {
      if (!last.current) last.current = now;
      const frameMs = (payload.dt * 1000) / Number(speed);
      if (now - last.current >= frameMs) {
        last.current = now;
        setFrame((f) => {
          if (f + 1 >= nFrames) {
            setPlaying(false);
            return f;
          }
          return f + 1;
        });
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      last.current = 0;
    };
  }, [playing, speed, nFrames, payload]);

  const f = payload?.frames[frame];
  const t = f?.t ?? 0;
  const feedSoFar = React.useMemo(
    () => (payload ? payload.feed.filter((e) => e.t <= t + 1e-6) : []),
    [payload, t]
  );
  const order = payload?.order_frames[frame] ?? [];

  const cars: MapCar[] = React.useMemo(() => {
    if (!payload || !f) return [];
    return payload.drivers.map((d) => ({
      key: d.id,
      x: f.x[d.index],
      y: f.y[d.index],
      label: d.id.replace("DRV_", "#"),
      color:
        focus === d.index
          ? "var(--series-2)"
          : conflictNow(payload, t, d.index)
          ? "var(--serious)"
          : "var(--series-1)",
      highlight: focus === d.index,
      dim: focus !== null && focus !== d.index,
      braking: f.brake[d.index],
    }));
  }, [payload, f, focus, t]);

  // Rolling conflict count for the timeline strip.
  const timeline = React.useMemo(() => {
    if (!payload) return [];
    const bins = 60;
    const step = payload.duration / bins;
    const counts = Array.from({ length: bins }, () => 0);
    for (const e of payload.feed) {
      if (e.event_type !== "conflict") continue;
      const i = Math.min(bins - 1, Math.max(0, Math.floor(e.t / step)));
      counts[i] += 1;
    }
    return counts.map((c, i) => ({ x: i * step, y: c }));
  }, [payload]);

  const s = payload?.summary ?? {};

  return (
    <>
      <PageHeader
        title="Live simulation"
        lede="Execute a single scenario and watch it unfold. The run is simulated in full first, then played back — so pause, scrub and speed are exact, and re-running the same seed reproduces it precisely."
        right={
          payload && (
            <div className="text-right">
              <div className="num text-[13px] text-ink">{clock(t)}</div>
              <div className="text-[10px] text-ink-3">
                seed {payload.seed} · {dec(Number(s.wall_time_ms), 0)} ms to simulate
              </div>
            </div>
          )
        }
      />

      {/* ------------------------------------------------------- controls --- */}
      <Panel title="Scenario" className="mb-3">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <label className="flex flex-col gap-1">
            <span className="label-xs">Seed</span>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
              className="num rounded border border-line-strong bg-surface-2 px-2 py-1.5 text-[12px] text-ink"
            />
          </label>
          <Select
            label="Weather"
            value={weather}
            onChange={setWeather}
            options={WEATHER_ORDER.map((w) => ({ value: w, label: WEATHER_LABEL[w] }))}
          />
          <Slider
            label="Cars"
            value={nCars}
            min={4}
            max={22}
            onChange={setNCars}
            format={(v) => String(v)}
          />
          <Slider
            label="Traffic density"
            value={density}
            min={0.05}
            max={1}
            step={0.05}
            onChange={setDensity}
            format={(v) => v.toFixed(2)}
            hint="Sets the nominal starting gap. Actual density is re-measured during the run."
          />
          <Slider
            label="Error rate ×"
            value={errMult}
            min={0}
            max={3}
            step={0.1}
            onChange={setErrMult}
            format={(v) => `${v.toFixed(1)}×`}
            hint="Scales every human-error rate in the assumptions registry."
          />
          <Slider
            label="Track width ×"
            value={widthMult}
            min={0.8}
            max={1.3}
            step={0.05}
            onChange={setWidthMult}
            format={(v) => `${v.toFixed(2)}×`}
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <Slider
            label="Duration"
            value={duration}
            min={20}
            max={150}
            step={5}
            onChange={setDuration}
            format={(v) => `${v} s`}
          />
          <Button variant="primary" onClick={run} disabled={busy || apiOnline === false}>
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
            {busy ? "Simulating" : "Run simulation"}
          </Button>
          {payload && (
            <span className="text-[11px] text-ink-3">
              Measured density {dec(Number(s.measured_traffic_density), 2)} · grip{" "}
              {dec(Number(payload.environment.grip), 2)} · visibility{" "}
              {dec(Number(payload.environment.visibility), 2)}
            </span>
          )}
        </div>
      </Panel>

      {error ? <ErrorState error={error} onRetry={run} /> : null}

      {!payload ? (
        busy ? (
          <Skeleton h={420} />
        ) : (
          <Panel>
            <p className="py-10 text-center text-[12.5px] text-ink-3">
              Configure a scenario above and run it. Nothing is displayed until the
              engine has produced a trajectory.
            </p>
          </Panel>
        )
      ) : (
        <>
          {/* --------------------------------------------- top summary --- */}
          <div className="mb-3 grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
            <StatTile label="Conflicts" value={int(Number(s.n_conflicts))} />
            <StatTile
              label="Critical"
              value={int(Number(s.n_critical))}
              tone="serious"
              glyph={SEVERITY.CRITICAL.glyph}
            />
            <StatTile
              label="Contacts"
              value={int(Number(s.n_collisions))}
              tone="critical"
              glyph={SEVERITY.INCIDENT.glyph}
              sub={`+ ${int(Number(s.n_light_contacts))} light`}
            />
            <StatTile label="Min TTC" value={sec(s.n_conflicts ? Number(s.min_ttc) : null)} />
            <StatTile
              label="Overtakes"
              value={int(Number(s.n_overtakes_completed))}
              sub={`${int(Number(s.n_overtake_attempts))} attempts`}
            />
            <StatTile
              label="Driver errors"
              value={int(Number(s.n_driver_errors))}
              sub={`${int(Number(s.n_off_track))} excursions · ${int(Number(s.n_spins))} spins`}
            />
          </div>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,280px)_minmax(0,300px)]">
            {/* ------------------------------------------------- circuit --- */}
            <Panel
              title="Circuit"
              right={
                <div className="flex items-center gap-1.5">
                  <Button size="sm" onClick={() => setFrame(0)} title="Restart">
                    <RotateCcw size={12} />
                  </Button>
                  <Button size="sm" variant="primary" onClick={() => setPlaying((p) => !p)}>
                    {playing ? <Pause size={12} /> : <Play size={12} />}
                  </Button>
                  <SegmentedControl value={speed} onChange={setSpeed} options={SPEEDS} size="sm" />
                </div>
              }
            >
              {track && <CircuitMap track={track} height={382} cars={cars} showCornerLabels />}
              <div className="mt-2">
                <input
                  type="range"
                  min={0}
                  max={Math.max(nFrames - 1, 0)}
                  value={frame}
                  onChange={(e) => {
                    setPlaying(false);
                    setFrame(Number(e.target.value));
                  }}
                  className="h-1 w-full cursor-pointer appearance-none rounded bg-surface-3 accent-[color:var(--accent)]"
                  aria-label="Playback position"
                />
                <div className="mt-1.5 flex items-center justify-between">
                  <SeverityLegend />
                  <span className="num text-[10.5px] text-ink-3">
                    {clock(t)} / {clock(payload.duration)}
                  </span>
                </div>
              </div>
            </Panel>

            {/* --------------------------------------------- timing tower --- */}
            <Panel title="Field" subtitle="Ordered by distance covered. Click to follow." dense>
              <ol className="max-h-[440px] space-y-[2px] overflow-y-auto">
                {order.map((idx, pos) => {
                  const d = payload.drivers[idx];
                  if (!d || !f) return null;
                  const inConflict = conflictNow(payload, t, idx);
                  return (
                    <li key={d.id}>
                      <button
                        onClick={() => setFocus(focus === idx ? null : idx)}
                        className={`flex w-full items-center gap-2 rounded px-1.5 py-[3px] text-left transition-colors ${
                          focus === idx ? "bg-surface-3" : "hover:bg-surface-2"
                        }`}
                      >
                        <span className="num w-[16px] shrink-0 text-[10px] text-ink-3">
                          {pos + 1}
                        </span>
                        <span
                          className="h-[6px] w-[6px] shrink-0 rounded-full"
                          style={{
                            background: inConflict ? "var(--serious)" : "var(--series-1)",
                          }}
                          aria-hidden
                        />
                        <span className="num w-[44px] shrink-0 text-[11px] text-ink">
                          {d.id.replace("DRV_", "#")}
                        </span>
                        <span className="num w-[46px] shrink-0 text-right text-[11px] text-ink-2">
                          {dec(f.speed_kph[idx], 0)}
                        </span>
                        <span className="truncate text-[9.5px] text-ink-3">
                          {DECISION_LABEL[f.decision[idx]] ?? f.decision[idx]}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <p className="mt-1.5 text-[9.5px] text-ink-3">
                Speed in km/h. A dot turns amber while that car is inside a flagged
                conflict.
              </p>
            </Panel>

            {/* --------------------------------------------- event stream --- */}
            <Panel
              title="Event stream"
              subtitle={`${feedSoFar.length} of ${payload.feed.length} events`}
              dense
            >
              <ol className="max-h-[440px] space-y-1.5 overflow-y-auto">
                {feedSoFar
                  .slice()
                  .reverse()
                  .map((e, i) => {
                    const sev = SEVERITY[e.severity as SeverityKey];
                    return (
                      <li key={i}>
                        <button
                          onClick={() => {
                            setPlaying(false);
                            setFrame(Number(e.stream_frame));
                            if (typeof e.driver_a_index === "number")
                              setFocus(Number(e.driver_a_index));
                          }}
                          className="flex w-full gap-2 rounded px-1 py-[2px] text-left hover:bg-surface-2"
                        >
                          <span className="num w-[48px] shrink-0 text-[10px] text-ink-3">
                            {clock(e.t)}
                          </span>
                          <span
                            className="num mt-[1px] shrink-0 text-[10.5px]"
                            style={{ color: sev?.color ?? "var(--text-muted)" }}
                            aria-hidden
                          >
                            {sev?.glyph ?? "·"}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[11px] text-ink">
                              {e.event_type === "conflict"
                                ? `${sev?.label ?? ""} conflict`
                                : EVENT_TYPE_LABEL[e.event_type] ?? e.event_type}
                            </span>
                            <span className="block truncate text-[10px] text-ink-3">
                              {String(e.location)}
                              {e.driver_a ? ` · ${e.driver_a}` : ""}
                              {e.driver_b ? ` → ${e.driver_b}` : ""}
                              {e.min_ttc !== undefined && e.min_ttc !== null
                                ? ` · TTC ${dec(Number(e.min_ttc), 2)}s`
                                : ""}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
              </ol>
            </Panel>
          </div>

          {/* --------------------------------------- telemetry timeline --- */}
          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Panel
              title="Conflict timeline"
              subtitle="Flagged conflicts per time bin across the whole run."
            >
              <LineChart
                series={[
                  {
                    key: "conflicts",
                    label: "Conflicts",
                    color: "var(--series-2)",
                    points: timeline,
                  },
                ]}
                height={140}
                xLabel="time (s)"
                yLabel="conflicts"
                xFormat={(v) => v.toFixed(0)}
                yFormat={(v) => v.toFixed(0)}
                area
                refLines={[{ y: 0, label: "", color: "transparent" }]}
              />
            </Panel>

            <Panel
              title={
                focus !== null
                  ? `Telemetry — ${payload.drivers[focus].id} (${
                      ARCHETYPE_SHORT[payload.drivers[focus].archetype] ??
                      payload.drivers[focus].archetype
                    })`
                  : "Telemetry"
              }
              subtitle={focus === null ? "Select a car in the field list to follow it." : undefined}
            >
              {focus === null ? (
                <p className="py-8 text-center text-[12px] text-ink-3">No car selected.</p>
              ) : (
                <>
                  <LineChart
                    series={[
                      {
                        key: "speed",
                        label: "Speed (km/h)",
                        color: "var(--series-1)",
                        points: payload.frames.map((fr) => ({
                          x: fr.t,
                          y: fr.speed_kph[focus],
                        })),
                      },
                    ]}
                    height={140}
                    xLabel="time (s)"
                    yLabel="km/h"
                    xFormat={(v) => v.toFixed(0)}
                    yFormat={(v) => v.toFixed(0)}
                  />
                  <div className="mt-2 grid grid-cols-4 gap-3 border-t border-line pt-2.5">
                    <Metric
                      label="Speed"
                      value={`${dec(f?.speed_kph[focus], 0)} km/h`}
                    />
                    <Metric label="Accel" value={`${dec(f?.accel[focus], 1)} m/s²`} />
                    <Metric label="Brake" value={`${Math.round((f?.brake[focus] ?? 0) * 100)}%`} />
                    <Metric label="Offset" value={`${dec(f?.d[focus], 2)} m`} />
                    <Metric
                      label="Aggression"
                      value={dec(payload.drivers[focus].aggression, 2)}
                    />
                    <Metric
                      label="Reaction"
                      value={`${dec(payload.drivers[focus].reaction_time, 2)} s`}
                    />
                    <Metric
                      label="Late braking"
                      value={dec(payload.drivers[focus].late_braking_tendency, 2)}
                    />
                    <Metric
                      label="Defensive"
                      value={dec(payload.drivers[focus].defensive_tendency, 2)}
                    />
                  </div>
                  <Caveat>
                    These are the perturbed parameters this agent actually raced with in
                    this run, not the archetype's nominal values.
                  </Caveat>
                </>
              )}
            </Panel>
          </div>

          {payload.conflicts.length > 0 && (
            <div className="mt-3">
              <Panel
                title="Conflicts recorded in this run"
                subtitle="Click to jump to the moment of minimum TTC."
                dense
              >
                <div className="flex flex-wrap gap-1.5">
                  {payload.conflicts.map((c, i) => {
                    const sev = SEVERITY[c.severity as SeverityKey];
                    return (
                      <button
                        key={i}
                        onClick={() => {
                          setPlaying(false);
                          setFrame(Math.min(Math.floor(c.timestep / 2), nFrames - 1));
                          setFocus(c.driver_a_index);
                        }}
                        className="rounded border px-2 py-1 text-left transition-colors hover:bg-surface-2"
                        style={{ borderColor: `${sev?.color ?? "var(--border-strong)"}55` }}
                      >
                        <span className="flex items-center gap-1.5">
                          <span className="num text-[10px]" style={{ color: sev?.color }} aria-hidden>
                            {sev?.glyph}
                          </span>
                          <span className="num text-[11px] text-ink">
                            {dec(c.min_ttc, 2)}s
                          </span>
                          <span className="text-[10px] text-ink-3">
                            {c.driver_a}→{c.driver_b}
                          </span>
                        </span>
                        <span className="mt-0.5 block text-[9.5px] text-ink-3">
                          {c.location} · {CONFLICT_TYPE_LABEL[c.conflict_type] ?? c.conflict_type}
                        </span>
                      </button>
                    );
                  })}
                </div>
                <Caveat>{payload.note}</Caveat>
              </Panel>
            </div>
          )}
        </>
      )}
    </>
  );
}

/** Is this car inside a flagged conflict at time t? */
function conflictNow(p: LivePayload, t: number, idx: number): boolean {
  return p.conflicts.some(
    (c) =>
      Math.abs(c.t_min_ttc - t) < 0.6 &&
      (c.driver_a_index === idx || c.driver_b_index === idx)
  );
}
