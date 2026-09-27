"use client";

import { FlaskConical, Loader2 } from "lucide-react";
import React from "react";

import { HBarChart } from "../../components/charts";
import { JobProgress, Metric, PageHeader } from "../../components/Common";
import {
  Badge,
  Button,
  Caveat,
  ErrorState,
  Panel,
  Select,
  Skeleton,
  Slider,
  Tabs,
} from "../../components/ui";
import {
  api,
  ExperimentResult,
  InterventionPreset,
  InterventionResult,
} from "../../lib/api";
import { dec, int, pct, signed } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import { WEATHER_LABEL, WEATHER_ORDER } from "../../lib/theme";

type Tab = "intervention" | "experiments";

export default function WhatIfPage() {
  const [tab, setTab] = React.useState<Tab>("intervention");
  return (
    <>
      <PageHeader
        title="What-if lab"
        lede="Change one thing and re-run the identical scenarios. Baseline and intervention share their seeds, so each pair has the same grid order, the same error draws and the same weather jitter — any difference is attributable to the change."
      />
      <Tabs
        tabs={[
          { value: "intervention", label: "Paired intervention" },
          { value: "experiments", label: "Controlled experiments" },
        ]}
        active={tab}
        onChange={setTab}
      />
      <div className="mt-3">
        {tab === "intervention" ? <InterventionLab /> : <ExperimentLab />}
      </div>
    </>
  );
}

/* --------------------------------------------------------- intervention --- */

function InterventionLab() {
  const { meta, jobs, watchJob } = useApp();
  const presets = meta?.intervention_presets ?? [];
  const [presetId, setPresetId] = React.useState<string>("");
  const [nRuns, setNRuns] = React.useState(200);
  const [weather, setWeather] = React.useState("");
  const [nCars, setNCars] = React.useState(22);
  const [density, setDensity] = React.useState(0.7);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);
  const [result, setResult] = React.useState<InterventionResult | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!presetId && presets.length) setPresetId(presets[0].id);
  }, [presets, presetId]);

  const preset: InterventionPreset | undefined = presets.find((p) => p.id === presetId);
  const job = jobs.find((j) => j.job_id === jobId);

  React.useEffect(() => {
    if (job?.status === "complete" && job.result) {
      setResult(job.result as unknown as InterventionResult);
    }
  }, [job]);

  const run = async () => {
    if (!preset) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const j = await api.whatIf({
        n_runs: nRuns,
        changes: preset.changes,
        pin: {
          ...(weather ? { weather } : {}),
          n_cars: nCars,
          traffic_density: density,
        },
        label: preset.name,
      });
      setJobId(j.job_id);
      watchJob(j);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const keyOutcomes = [
    "n_critical",
    "n_conflicts",
    "n_near_misses",
    "n_collisions",
    "n_off_track",
    "min_ttc",
  ];

  return (
    <div className="grid gap-3">
      <Panel title="Configure the experiment">
        {err ? <ErrorState error={err} /> : null}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <Select
            label="Intervention"
            value={presetId}
            onChange={setPresetId}
            options={presets.map((p) => ({ value: p.id, label: p.name }))}
          />
          <Select
            label="Weather (held fixed)"
            value={weather}
            onChange={setWeather}
            options={[
              { value: "", label: "Sampled as usual" },
              ...WEATHER_ORDER.map((w) => ({ value: w, label: WEATHER_LABEL[w] })),
            ]}
          />
          <Slider label="Cars" value={nCars} min={6} max={22} onChange={setNCars} />
          <Slider
            label="Traffic density"
            value={density}
            min={0.1}
            max={1}
            step={0.05}
            onChange={setDensity}
            format={(v) => v.toFixed(2)}
          />
          <Slider
            label="Seed-matched pairs"
            value={nRuns}
            min={40}
            max={600}
            step={20}
            onChange={setNRuns}
            format={(v) => int(v)}
            hint="Each pair is one baseline run and one intervention run sharing a seed."
          />
        </div>

        {preset && (
          <div className="mt-3 rounded border border-line bg-surface-2/40 px-3 py-2">
            <p className="text-[12px] text-ink-2">{preset.description}</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(preset.changes).map(([k, v]) => (
                <Badge key={k} color="var(--accent)">
                  {k.replace(/_/g, " ")} = {String(v)}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <Button
            variant="primary"
            onClick={run}
            disabled={busy || !preset || job?.status === "running"}
          >
            {busy || job?.status === "running" ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <FlaskConical size={12} />
            )}
            Run baseline and intervention
          </Button>
          <span className="text-[11px] text-ink-3">
            {int(nRuns * 2)} simulations — {int(nRuns)} matched pairs
          </span>
        </div>
        {job && job.status === "running" && <JobProgress job={job} />}
        {job?.error && <div className="mt-3"><ErrorState error={new Error(job.error)} /></div>}
      </Panel>

      {result && (
        <>
          <Panel title="Result" note={result.note}>
            <p className="text-[13px] leading-relaxed text-ink">{result.headline}</p>
            <div className="mt-3 grid grid-cols-2 gap-x-5 gap-y-2 border-t border-line pt-2.5 sm:grid-cols-4">
              <Metric label="Matched pairs" value={int(result.n_pairs)} />
              <Metric label="Seed base" value={int(result.seed_base)} />
              <Metric
                label="Baseline batch"
                value={<span className="text-[10.5px]">{result.baseline_batch_id}</span>}
              />
              <Metric
                label="Intervention batch"
                value={<span className="text-[10.5px]">{result.intervention_batch_id}</span>}
              />
            </div>
          </Panel>

          <Panel
            title="Before, after, difference"
            subtitle="Paired differences with their standard error, so an effect can be told apart from noise."
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr>
                    <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-left">
                      Measure
                    </th>
                    {["Baseline", "Intervention", "Difference", "± SEM", "Better", "Worse", "Same", "Exceeds noise"].map(
                      (h) => (
                        <th
                          key={h}
                          className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-right"
                        >
                          {h}
                        </th>
                      )
                    )}
                  </tr>
                </thead>
                <tbody>
                  {result.outcomes
                    .filter((o) => result.paired[o.key])
                    .map((o) => {
                      const p = result.paired[o.key];
                      const base = result.baseline[o.key] as { mean: number | null };
                      const int_ = result.intervention[o.key] as { mean: number | null };
                      const digits = o.key.startsWith("min_") ? 3 : 3;
                      const improved = p.mean_difference < 0;
                      const key = keyOutcomes.includes(o.key);
                      return (
                        <tr
                          key={o.key}
                          className={`border-b border-line/60 ${key ? "" : "opacity-70"}`}
                        >
                          <td className="px-2 py-1.5 text-ink-2">{o.label}</td>
                          <td className="num px-2 py-1.5 text-right text-ink">
                            {dec(base?.mean, digits)}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink">
                            {dec(int_?.mean, digits)}
                          </td>
                          <td
                            className="num px-2 py-1.5 text-right"
                            style={{
                              color: p.exceeds_noise
                                ? improved
                                  ? "var(--good)"
                                  : "var(--serious)"
                                : "var(--text-secondary)",
                            }}
                          >
                            {signed(p.mean_difference, digits)}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink-3">
                            {dec(p.sem, digits)}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink-3">
                            {int(p.improved_pairs)}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink-3">
                            {int(p.worsened_pairs)}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink-3">
                            {int(p.unchanged_pairs)}
                          </td>
                          <td className="px-2 py-1.5 text-right">
                            {p.exceeds_noise === null ? (
                              <span className="text-ink-3">—</span>
                            ) : p.exceeds_noise ? (
                              <Badge color="var(--good)" glyph="✓">
                                yes
                              </Badge>
                            ) : (
                              <Badge glyph="·">no</Badge>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
            <Caveat>
              &quot;Exceeds noise&quot; means the paired mean difference is more than two
              standard errors from zero. It is a rough indicator, not a hypothesis test,
              and a difference that clears it is still a difference in
              <em> simulated </em> conflict frequency under this model&apos;s assumptions.
            </Caveat>
          </Panel>

          <Panel
            title="Effect by measure"
            subtitle="Paired mean difference; negative means the intervention reduced it."
          >
            <HBarChart
              data={result.outcomes
                .filter((o) => result.paired[o.key] && keyOutcomes.includes(o.key))
                .map((o) => {
                  const p = result.paired[o.key];
                  return {
                    key: o.key,
                    label: o.label,
                    value: Math.abs(p.mean_difference),
                    color:
                      p.mean_difference < 0 ? "var(--series-3)" : "var(--series-2)",
                    glyph: p.mean_difference < 0 ? "↓" : "↑",
                    tip: [
                      { label: "Difference", value: signed(p.mean_difference, 4) },
                      { label: "SEM", value: dec(p.sem, 4) },
                      { label: "Pairs improved", value: int(p.improved_pairs) },
                      { label: "Pairs worsened", value: int(p.worsened_pairs) },
                      {
                        label: "Exceeds noise",
                        value: p.exceeds_noise === null ? "—" : p.exceeds_noise ? "yes" : "no",
                      },
                    ],
                  };
                })}
              labelWidth={196}
              valueFormat={(v) => dec(v, 3)}
            />
            <div className="mt-2 flex gap-4 border-t border-line pt-2">
              <span className="flex items-center gap-1.5 text-[10.5px] text-ink-3">
                <span className="num" style={{ color: "var(--series-3)" }} aria-hidden>
                  ↓
                </span>
                reduced by the intervention
              </span>
              <span className="flex items-center gap-1.5 text-[10.5px] text-ink-3">
                <span className="num" style={{ color: "var(--series-2)" }} aria-hidden>
                  ↑
                </span>
                increased by the intervention
              </span>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- experiments --- */

function ExperimentLab() {
  const { meta, jobs, watchJob } = useApp();
  const specs = meta?.experiments ?? [];
  const [key, setKey] = React.useState("");
  const [runsPerArm, setRunsPerArm] = React.useState(150);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<ExperimentResult | null>(null);
  const [outcome, setOutcome] = React.useState("n_critical");

  const stored = useFetch(() => api.storedExperiments(), []);
  const [storedId, setStoredId] = React.useState<string | null>(null);
  const storedDetail = useFetch(
    storedId ? () => api.storedExperiment(storedId) : null,
    [storedId]
  );

  React.useEffect(() => {
    if (!key && specs.length) setKey(specs[0].key);
  }, [specs, key]);

  const job = jobs.find((j) => j.job_id === jobId);
  React.useEffect(() => {
    if (job?.status === "complete" && job.result) {
      setResult(job.result as unknown as ExperimentResult);
    }
  }, [job]);

  const spec = specs.find((s) => s.key === key);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const j = await api.runExperiment({ key, runs_per_arm: runsPerArm });
      setJobId(j.job_id);
      watchJob(j);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const shown =
    result ??
    (storedDetail.data?.results as unknown as ExperimentResult | undefined) ??
    null;

  return (
    <div className="grid gap-3">
      <Panel
        title="Controlled experiments"
        subtitle="Every arm shares a seed base and differs only in the pinned dimension."
      >
        {err ? <ErrorState error={err} /> : null}
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Experiment"
            value={key}
            onChange={setKey}
            className="w-[280px]"
            options={specs.map((s) => ({
              value: s.key,
              label: `${s.number}. ${s.name}`,
            }))}
          />
          <Slider
            label="Runs per arm"
            value={runsPerArm}
            min={40}
            max={600}
            step={20}
            onChange={setRunsPerArm}
            format={(v) => int(v)}
          />
          <Button variant="primary" onClick={run} disabled={busy || job?.status === "running"}>
            {busy || job?.status === "running" ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <FlaskConical size={12} />
            )}
            Run experiment
          </Button>
          {spec && (
            <span className="text-[11px] text-ink-3">
              {spec.arms.length} arms × {int(runsPerArm)} = {int(spec.arms.length * runsPerArm)}{" "}
              simulations
            </span>
          )}
        </div>
        {spec && (
          <p className="mt-2.5 border-t border-line pt-2.5 text-[12px] text-ink-2">
            <span className="text-ink-3">Question:</span> {spec.question}
          </p>
        )}
        {job && job.status === "running" && <JobProgress job={job} />}
        {job?.error && <div className="mt-3"><ErrorState error={new Error(job.error)} /></div>}
      </Panel>

      {stored.data && stored.data.experiments.length > 0 && (
        <Panel title="Previously run experiments" dense>
          <div className="flex flex-wrap gap-1.5">
            {stored.data.experiments.map((e) => (
              <button
                key={e.id}
                onClick={() => {
                  setStoredId(e.id);
                  setResult(null);
                }}
                className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                  storedId === e.id
                    ? "border-[color:var(--accent)] bg-[color:var(--accent)]/12 text-ink"
                    : "border-line text-ink-3 hover:border-line-strong hover:text-ink-2"
                }`}
              >
                {e.name}
                <span className="ml-1.5 text-ink-3">{e.kind}</span>
              </button>
            ))}
          </div>
        </Panel>
      )}

      {shown && shown.arms && (
        <>
          <Panel
            title={`${shown.number}. ${shown.name}`}
            subtitle={shown.question}
            right={
              <Select
                label=""
                value={outcome}
                onChange={setOutcome}
                options={(shown.outcomes ?? []).map((o) => ({ value: o.key, label: o.label }))}
              />
            }
            note={shown.note}
          >
            <HBarChart
              data={shown.arms.map((a) => {
                const st = a.stats[outcome] as { mean: number | null; sem: number | null };
                return {
                  key: a.label,
                  label: a.label,
                  value: Number(st?.mean ?? 0),
                  tip: [
                    { label: "Mean", value: dec(st?.mean, 4) },
                    { label: "SEM", value: dec(st?.sem, 4) },
                    { label: "Runs", value: int(Number(a.stats.n_runs)) },
                    {
                      label: "Runs with a critical conflict",
                      value: pct(Number(a.stats.fraction_runs_with_critical), 1),
                    },
                  ],
                };
              })}
              labelWidth={148}
              valueFormat={(v) => dec(v, 3)}
            />

            <div className="mt-3 overflow-x-auto border-t border-line pt-2.5">
              <table className="w-full text-[11.5px]">
                <thead>
                  <tr>
                    <th className="label-xs !text-[9px] border-b border-line-strong px-1.5 py-1 text-left">
                      Arm
                    </th>
                    {["Runs", "Conflicts", "Critical", "Near miss", "Contact", "Excursion", "Min TTC", "% runs critical"].map(
                      (h) => (
                        <th
                          key={h}
                          className="label-xs !text-[9px] border-b border-line-strong px-1.5 py-1 text-right"
                        >
                          {h}
                        </th>
                      )
                    )}
                  </tr>
                </thead>
                <tbody>
                  {shown.arms.map((a) => {
                    const g = (k: string) =>
                      (a.stats[k] as { mean: number | null })?.mean ?? null;
                    return (
                      <tr key={a.label} className="border-b border-line/60">
                        <td className="px-1.5 py-1 text-ink-2">{a.label}</td>
                        <td className="num px-1.5 py-1 text-right text-ink-3">
                          {int(Number(a.stats.n_runs))}
                        </td>
                        <td className="num px-1.5 py-1 text-right text-ink">{dec(g("n_conflicts"), 2)}</td>
                        <td className="num px-1.5 py-1 text-right text-ink">{dec(g("n_critical"), 2)}</td>
                        <td className="num px-1.5 py-1 text-right text-ink">{dec(g("n_near_misses"), 2)}</td>
                        <td className="num px-1.5 py-1 text-right text-ink">{dec(g("n_collisions"), 3)}</td>
                        <td className="num px-1.5 py-1 text-right text-ink">{dec(g("n_off_track"), 2)}</td>
                        <td className="num px-1.5 py-1 text-right text-ink">{dec(g("min_ttc"), 3)}</td>
                        <td className="num px-1.5 py-1 text-right text-ink-2">
                          {pct(Number(a.stats.fraction_runs_with_critical), 1)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>

          {shown.deltas && shown.deltas.length > 0 && (
            <Panel
              title="Each arm against the first"
              subtitle="Difference, with the combined standard error alongside so a real effect can be told from noise."
            >
              <div className="grid gap-3 lg:grid-cols-2">
                {shown.deltas.map((d) => (
                  <div key={d.label} className="rounded border border-line bg-surface-2/40 p-2.5">
                    <p className="mb-2 text-[12px] text-ink">
                      {d.label}{" "}
                      <span className="text-ink-3">vs {d.baseline_label}</span>
                    </p>
                    <ul className="space-y-1">
                      {Object.entries(d.metrics)
                        .filter(([k]) =>
                          [
                            "n_conflicts",
                            "n_critical",
                            "n_near_misses",
                            "n_collisions",
                            "n_off_track",
                            "min_ttc",
                          ].includes(k)
                        )
                        .map(([k, m]) => (
                          <li key={k} className="flex items-baseline justify-between gap-2">
                            <span className="text-[11px] text-ink-3">{m.label}</span>
                            <span className="flex items-baseline gap-1.5">
                              <span
                                className="num text-[11.5px]"
                                style={{
                                  color: m.exceeds_noise
                                    ? m.absolute < 0
                                      ? "var(--good)"
                                      : "var(--serious)"
                                    : "var(--text-secondary)",
                                }}
                              >
                                {signed(m.absolute, 3)}
                              </span>
                              {m.relative !== null && (
                                <span className="num text-[10px] text-ink-3">
                                  ({signed(m.relative * 100, 1)}%)
                                </span>
                              )}
                              {m.exceeds_noise === false && (
                                <span className="text-[9px] text-ink-3">within noise</span>
                              )}
                            </span>
                          </li>
                        ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
