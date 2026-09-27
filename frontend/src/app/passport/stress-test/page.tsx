"use client";

import { ArrowRight, Loader2, Zap } from "lucide-react";
import Link from "next/link";
import React from "react";

import { PageHeader } from "../../../components/Common";
import { driverSummary, RequireCar, usePassportCatalogue } from "../../../components/passport";
import { Button, Caveat, ErrorState, Panel, Select } from "../../../components/ui";
import { dec, int } from "../../../lib/format";
import { Car, passportApi, StressJob } from "../../../lib/passport";
import { useApp } from "../../../lib/store";
import { WEATHER_LABEL, WEATHER_ORDER } from "../../../lib/theme";

export default function StressTestPage() {
  return (
    <>
      <PageHeader
        title="Stress test"
        lede="Race this car many times in the simulator before its next real race — same circuit and weather, a different seeded field each time — and predict how much life each part will use."
      />
      <RequireCar>{(car) => <Runner key={car.id} car={car} />}</RequireCar>
    </>
  );
}

function Runner({ car }: { car: Car }) {
  const { meta } = useApp();
  const { archetypes } = usePassportCatalogue();
  const [trackId, setTrackId] = React.useState("vale_park");
  const [weather, setWeather] = React.useState("DRY");
  const [nRaces, setNRaces] = React.useState("200");
  const [job, setJob] = React.useState<StressJob | null>(null);
  const [err, setErr] = React.useState<unknown>(null);

  const running = job?.status === "running";

  // Poll the job until it finishes. Stress-test jobs report through the
  // passport route so the finished job carries its full result.
  React.useEffect(() => {
    if (!job || job.status !== "running") return;
    const id = window.setInterval(async () => {
      try {
        setJob(await passportApi.stressJob(job.job_id));
      } catch (e) {
        setErr(e);
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [job]);

  const start = async () => {
    setErr(null);
    try {
      setJob(
        await passportApi.startStressTest(car.id, {
          track_id: trackId,
          weather,
          n_races: Number(nRaces),
        })
      );
    } catch (e) {
      setErr(e);
    }
  };

  const frac = job?.total ? Math.min(job.completed / job.total, 1) : 0;
  const result = job?.status === "complete" ? job.result : null;

  return (
    <div className="grid gap-3">
      <Panel title="Configure">
        {err ? <ErrorState error={err} /> : null}
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Circuit"
            value={trackId}
            onChange={setTrackId}
            className="w-[200px]"
            options={(meta?.tracks ?? [{ id: "vale_park", name: "Vale Park" }]).map((t) => ({
              value: t.id,
              label: t.name,
            }))}
          />
          <Select
            label="Weather"
            value={weather}
            onChange={setWeather}
            className="w-[150px]"
            options={WEATHER_ORDER.map((w) => ({ value: w, label: WEATHER_LABEL[w] }))}
          />
          <Select
            label="Simulated races"
            value={nRaces}
            onChange={setNRaces}
            className="w-[150px]"
            options={[
              { value: "50", label: "50 — quick" },
              { value: "200", label: "200 — default" },
              { value: "500", label: "500" },
              { value: "1000", label: "1,000" },
            ]}
          />
          <Button variant="primary" onClick={start} disabled={running}>
            {running ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
            {running ? "Running…" : "Run stress test"}
          </Button>
        </div>
        <p className="mt-3 text-[11.5px] text-ink-3">
          Driver: <span className="text-ink-2">{driverSummary(car.team_driver, archetypes)}</span>{" "}
          ·{" "}
          <Link href="/passport" className="underline decoration-dotted hover:text-ink-2">
            change in Garage
          </Link>
        </p>

        {job && (
          <div className="mt-3 rounded border border-line bg-surface-2/60 px-3 py-2.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[11.5px] text-ink-2">
                {job.label} <span className="text-ink-3">· {job.phase}</span>
              </span>
              <span className="num text-[11.5px] text-ink">
                {int(job.completed)} / {int(job.total)}
              </span>
            </div>
            <div className="mt-2 h-[3px] overflow-hidden rounded-full bg-surface-3">
              <div
                className="h-full rounded-full transition-[width] duration-300"
                style={{ width: `${frac * 100}%`, background: "var(--accent)" }}
              />
            </div>
            {job.error && (
              <p className="mt-2 text-[11px]" style={{ color: "var(--critical)" }}>
                {job.error}
              </p>
            )}
          </div>
        )}
      </Panel>

      {result && (
        <Panel
          title="Finished"
          right={
            <Link href="/passport/readiness">
              <Button size="sm" variant="primary">
                Readiness report <ArrowRight size={11} />
              </Button>
            </Link>
          }
          note={result.note}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Summary label="Parts crossing replace threshold" value={int(result.parts_crossing_red_count)} sub="in at least one simulated race" />
            <Summary label="Close calls" value={int(result.n_close_calls)} sub="races with any pair below 0.8 s TTC" />
            <Summary label="Cost forecast" value={dec(result.cost_forecast.total, 0)} sub="illustrative, per race" />
          </div>
        </Panel>
      )}

      <Caveat>
        Every run is an ordinary simulator run with this car in grid slot 1, so it also appears
        in Replay and the other analysis screens under its own batch.
      </Caveat>
    </div>
  );
}

function Summary({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <p className="label-xs">{label}</p>
      <p className="num mt-1 text-[24px] font-medium leading-none text-ink">{value}</p>
      <p className="mt-1 text-[11px] text-ink-3">{sub}</p>
    </div>
  );
}
