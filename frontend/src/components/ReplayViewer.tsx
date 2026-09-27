"use client";

/**
 * Incident replay.
 *
 * Plays back a stored trajectory window around the moment of minimum TTC. The
 * window is real recorded trajectory — the backend regenerates it by re-running
 * the scenario from its seed, which is bit-for-bit identical to the original run —
 * so the TTC trace under the timeline is the measured quantity, not a redrawing.
 */

import { Pause, Play, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import React from "react";

import type { Replay, TrackGeometry } from "../lib/api";
import { clock, dec, int, sec } from "../lib/format";
import {
  ARCHETYPE_SHORT,
  DECISION_LABEL,
  ERROR_LABEL,
  EVENT_TYPE_LABEL,
  SEVERITY,
  SeverityKey,
} from "../lib/theme";
import { CircuitMap, MapCar } from "./CircuitMap";
import { LineChart } from "./charts";
import { Badge, Button, Caveat, Panel, SegmentedControl } from "./ui";

const SPEEDS = [
  { value: "0.25", label: "0.25×" },
  { value: "0.5", label: "0.5×" },
  { value: "1", label: "1×" },
  { value: "2", label: "2×" },
];

export function ReplayViewer({
  replay,
  track,
  ttcThreshold,
  criticalThreshold,
}: {
  replay: Replay;
  track: TrackGeometry;
  ttcThreshold: number;
  criticalThreshold: number;
}) {
  const [frame, setFrame] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState("0.5");
  const raf = React.useRef<number | null>(null);
  const last = React.useRef<number>(0);

  const nFrames = replay.n_frames;
  const focusFrame = React.useMemo(() => {
    let best = 0;
    let bd = Infinity;
    replay.frame_times.forEach((t, i) => {
      const d = Math.abs(t - replay.t_focus);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    return best;
  }, [replay]);

  // Start a couple of seconds before the event so the lead-in is visible.
  React.useEffect(() => {
    setFrame(0);
    setPlaying(true);
  }, [replay.run_id]);

  React.useEffect(() => {
    if (!playing) {
      if (raf.current) cancelAnimationFrame(raf.current);
      return;
    }
    const tick = (now: number) => {
      if (!last.current) last.current = now;
      const dtMs = now - last.current;
      const frameMs = (replay.dt * 1000) / Number(speed);
      if (dtMs >= frameMs) {
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
  }, [playing, speed, nFrames, replay.dt]);

  const t = replay.frame_times[frame] ?? 0;
  const focusCars = replay.cars.filter((c) => c.is_focus);

  const cars: MapCar[] = replay.cars.map((c) => ({
    key: c.driver_id,
    x: c.x[frame] ?? c.x[0],
    y: c.y[frame] ?? c.y[0],
    label: c.driver_id.replace("DRV_", "#"),
    color: c.is_focus
      ? c.driver_index === replay.focus_drivers[0]
        ? "var(--series-2)"
        : "var(--series-1)"
      : "var(--text-muted)",
    highlight: c.is_focus,
    dim: !c.is_focus,
    braking: c.brake[frame],
  }));

  const trails = focusCars.map((c) => ({
    x: c.x.slice(Math.max(0, frame - 40), frame + 1),
    y: c.y.slice(Math.max(0, frame - 40), frame + 1),
    color: c.driver_index === replay.focus_drivers[0] ? "var(--series-2)" : "var(--series-1)",
  }));

  const ttcPoints = replay.ttc_trace.map((p) => ({ x: p.t, y: p.ttc }));
  const gapPoints = replay.ttc_trace.map((p) => ({ x: p.t, y: p.gap }));
  const closingPoints = replay.ttc_trace.map((p) => ({ x: p.t, y: p.closing_speed }));

  const activeEvents = replay.events.filter((e) => Math.abs(e.t - t) < 0.3);
  const pastEvents = replay.events.filter((e) => e.t <= t + 1e-6);
  const currentTtc = replay.ttc_trace.find((p) => Math.abs(p.t - t) < replay.dt / 1.5);

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-3">
        <Panel
          title="Replay"
          subtitle={`${clock(replay.t_start)} → ${clock(replay.t_end)} · minimum TTC at ${clock(
            replay.t_focus
          )}`}
          right={
            <div className="flex items-center gap-2">
              <span className="num text-[13px] text-ink">{clock(t)}</span>
              {currentTtc?.ttc !== null && currentTtc?.ttc !== undefined && (
                <Badge
                  color={
                    currentTtc.ttc <= criticalThreshold
                      ? SEVERITY.CRITICAL.color
                      : currentTtc.ttc <= ttcThreshold
                      ? SEVERITY.WARNING.color
                      : undefined
                  }
                  glyph={
                    currentTtc.ttc <= criticalThreshold
                      ? SEVERITY.CRITICAL.glyph
                      : currentTtc.ttc <= ttcThreshold
                      ? SEVERITY.WARNING.glyph
                      : undefined
                  }
                >
                  TTC {dec(currentTtc.ttc, 2)} s
                </Badge>
              )}
            </div>
          }
        >
          <CircuitMap
            track={track}
            height={340}
            cars={cars}
            trail={trails}
            showRacingLine
            showCornerLabels
          />

          {/* transport controls */}
          <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
            <Button size="sm" onClick={() => setFrame(0)} title="Restart">
              <RotateCcw size={12} />
            </Button>
            <Button
              size="sm"
              onClick={() => setFrame((f) => Math.max(0, f - 1))}
              title="Step back one frame"
            >
              <SkipBack size={12} />
            </Button>
            <Button size="sm" variant="primary" onClick={() => setPlaying((p) => !p)}>
              {playing ? <Pause size={12} /> : <Play size={12} />}
              {playing ? "Pause" : "Play"}
            </Button>
            <Button
              size="sm"
              onClick={() => setFrame((f) => Math.min(nFrames - 1, f + 1))}
              title="Step forward one frame"
            >
              <SkipForward size={12} />
            </Button>
            <Button size="sm" onClick={() => setFrame(focusFrame)} title="Jump to minimum TTC">
              Jump to conflict
            </Button>
            <SegmentedControl
              value={speed}
              onChange={setSpeed}
              options={SPEEDS}
              size="sm"
            />
            <span className="num ml-auto text-[10.5px] text-ink-3">
              frame {frame + 1}/{nFrames} · {int(1 / replay.dt)} Hz playback
            </span>
          </div>

          {/* scrubber with event ticks */}
          <div className="relative mt-2.5">
            <input
              type="range"
              min={0}
              max={nFrames - 1}
              value={frame}
              onChange={(e) => {
                setPlaying(false);
                setFrame(Number(e.target.value));
              }}
              className="h-1 w-full cursor-pointer appearance-none rounded bg-surface-3 accent-[color:var(--accent)]"
              aria-label="Replay position"
            />
            <div className="pointer-events-none absolute inset-x-0 top-0 h-1">
              {replay.events.map((e, i) => {
                const frac =
                  (e.t - replay.t_start) / Math.max(replay.t_end - replay.t_start, 1e-6);
                const sev = SEVERITY[e.severity as SeverityKey];
                return (
                  <span
                    key={i}
                    className="absolute top-[-3px] h-[7px] w-[2px] rounded-full"
                    style={{
                      left: `${Math.max(0, Math.min(1, frac)) * 100}%`,
                      background: sev?.color ?? "var(--text-muted)",
                    }}
                    title={`${clock(e.t)} ${EVENT_TYPE_LABEL[e.event_type] ?? e.event_type}`}
                  />
                );
              })}
              <span
                className="absolute top-[-5px] h-[11px] w-[2px]"
                style={{
                  left: `${
                    ((replay.t_focus - replay.t_start) /
                      Math.max(replay.t_end - replay.t_start, 1e-6)) *
                    100
                  }%`,
                  background: "var(--text-primary)",
                }}
                title="Minimum TTC"
              />
            </div>
          </div>
          {activeEvents.length > 0 && (
            <div className="fade-up mt-2 flex flex-wrap gap-1.5">
              {activeEvents.map((e, i) => {
                const sev = SEVERITY[e.severity as SeverityKey];
                return (
                  <Badge key={i} color={sev?.color} glyph={sev?.glyph}>
                    {EVENT_TYPE_LABEL[e.event_type] ?? e.event_type} · {e.driver_a}
                  </Badge>
                );
              })}
            </div>
          )}
        </Panel>

        {/* surrogate-measure traces */}
        <Panel
          title="Surrogate measures through the window"
          subtitle="Measured between the two cars involved, from their recorded trajectories."
        >
          <LineChart
            series={[
              {
                key: "ttc",
                label: "Time to collision (s)",
                color: "var(--series-2)",
                points: ttcPoints,
              },
            ]}
            height={150}
            xLabel="time (s)"
            yLabel="TTC (s)"
            xFormat={(v) => v.toFixed(1)}
            yFormat={(v) => v.toFixed(2)}
            refLines={[
              { y: ttcThreshold, label: `conflict ${ttcThreshold}s`, color: SEVERITY.WARNING.color },
              {
                y: criticalThreshold,
                label: `critical ${criticalThreshold}s`,
                color: SEVERITY.CRITICAL.color,
              },
            ]}
            note="TTC is undefined where the projected trajectories do not intersect; the line breaks there rather than being drawn as zero."
          />
          <div className="mt-2 grid gap-3 border-t border-line pt-2.5 sm:grid-cols-2">
            <LineChart
              series={[
                { key: "gap", label: "Separation (m)", color: "var(--series-1)", points: gapPoints },
              ]}
              height={124}
              xLabel="time (s)"
              yLabel="gap (m)"
              xFormat={(v) => v.toFixed(1)}
              yFormat={(v) => v.toFixed(0)}
            />
            <LineChart
              series={[
                {
                  key: "closing",
                  label: "Closing speed (m/s)",
                  color: "var(--series-3)",
                  points: closingPoints,
                },
              ]}
              height={124}
              xLabel="time (s)"
              yLabel="closing (m/s)"
              xFormat={(v) => v.toFixed(1)}
              yFormat={(v) => v.toFixed(0)}
              refLines={[{ y: 0, label: "separating below 0", color: "var(--text-muted)" }]}
            />
          </div>
        </Panel>
      </div>

      <div className="flex min-w-0 flex-col gap-3">
        {/* per-car telemetry at the current frame */}
        <Panel title="Telemetry at this instant" dense>
          <div className="space-y-2">
            {focusCars.map((c) => {
              const isA = c.driver_index === replay.focus_drivers[0];
              const color = isA ? "var(--series-2)" : "var(--series-1)";
              return (
                <div key={c.driver_id} className="rounded border border-line bg-surface-2/40 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5">
                      <span
                        className="inline-block h-[8px] w-[8px] rounded-full"
                        style={{ background: color }}
                        aria-hidden
                      />
                      <span className="text-[12px] font-medium text-ink">{c.driver_id}</span>
                      <span className="text-[10.5px] text-ink-3">
                        {ARCHETYPE_SHORT[c.archetype] ?? c.archetype}
                      </span>
                    </span>
                    <Badge>{DECISION_LABEL[c.decision[frame]] ?? c.decision[frame]}</Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-4 gap-2">
                    <Readout label="Speed" value={dec((c.speed[frame] ?? 0) * 3.6, 0)} unit="km/h" />
                    <Readout label="Accel" value={dec(c.accel[frame] ?? 0, 1)} unit="m/s²" />
                    <Readout label="Lateral" value={dec(c.lateral_rate[frame] ?? 0, 1)} unit="m/s" />
                    <Readout label="Offset" value={dec(c.d[frame] ?? 0, 2)} unit="m" />
                  </div>
                  <div className="mt-2 space-y-1">
                    <PedalBar label="Throttle" value={c.throttle[frame] ?? 0} color="var(--good)" />
                    <PedalBar label="Brake" value={c.brake[frame] ?? 0} color="var(--critical)" />
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        {/* event log up to now */}
        <Panel
          title="Events so far"
          subtitle="Everything recorded in this window up to the current instant."
        >
          {pastEvents.length === 0 ? (
            <p className="py-3 text-[11.5px] text-ink-3">Nothing recorded yet.</p>
          ) : (
            <ol className="space-y-1.5">
              {pastEvents
                .slice()
                .reverse()
                .map((e, i) => {
                  const sev = SEVERITY[e.severity as SeverityKey];
                  return (
                    <li key={i} className="flex items-start gap-2">
                      <span className="num w-[52px] shrink-0 text-[10.5px] text-ink-3">
                        {clock(e.t)}
                      </span>
                      <span
                        className="num mt-[1px] shrink-0 text-[11px]"
                        style={{ color: sev?.color }}
                        aria-hidden
                      >
                        {sev?.glyph}
                      </span>
                      <span className="min-w-0 text-[11.5px] leading-snug text-ink-2">
                        <span className="text-ink">
                          {EVENT_TYPE_LABEL[e.event_type] ?? e.event_type}
                        </span>{" "}
                        — {e.driver_a}
                        {e.driver_b ? ` → ${e.driver_b}` : ""} at {e.location}
                        {e.min_ttc !== null && e.min_ttc !== undefined
                          ? ` · TTC ${dec(e.min_ttc, 2)} s`
                          : ""}
                        {e.max_deceleration !== null && e.max_deceleration !== undefined
                          ? ` · ${dec(e.max_deceleration / 9.81, 1)} g`
                          : ""}
                      </span>
                    </li>
                  );
                })}
            </ol>
          )}
        </Panel>

        {replay.error_log.length > 0 && (
          <Panel
            title="Human-error events in this window"
            subtitle="Sampled from the configured error rates, which are modelling assumptions."
            dense
          >
            <ol className="space-y-1">
              {replay.error_log.map((e, i) => (
                <li key={i} className="flex items-baseline gap-2">
                  <span className="num w-[52px] shrink-0 text-[10.5px] text-ink-3">
                    {clock(e.t)}
                  </span>
                  <span className="text-[11.5px] text-ink-2">
                    {replay.cars.find((c) => c.driver_index === e.driver_index)?.driver_id ??
                      `#${e.driver_index}`}{" "}
                    — {ERROR_LABEL[e.kind] ?? e.kind}
                  </span>
                </li>
              ))}
            </ol>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Readout({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div>
      <div className="label-xs !text-[8.5px]">{label}</div>
      <div className="num text-[13px] leading-tight text-ink">
        {value}
        <span className="ml-0.5 text-[9px] text-ink-3">{unit}</span>
      </div>
    </div>
  );
}

function PedalBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="label-xs !text-[8.5px] w-[44px] shrink-0">{label}</span>
      <div className="h-[4px] flex-1 overflow-hidden rounded-full bg-surface-3">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }}
        />
      </div>
      <span className="num w-[30px] shrink-0 text-right text-[10px] text-ink-3">
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}
