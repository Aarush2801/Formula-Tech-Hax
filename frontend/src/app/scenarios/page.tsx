"use client";

import { ArrowRight, Loader2, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import React from "react";

import { HBarChart, LineChart } from "../../components/charts";
import {
  JobProgress,
  Metric,
  PageHeader,
  PatternCard,
  RequireBatch,
  SeverityBadge,
} from "../../components/Common";
import {
  Badge,
  Button,
  Caveat,
  DataTable,
  EmptyState,
  ErrorState,
  Panel,
  SegmentedControl,
  Skeleton,
  Tabs,
} from "../../components/ui";
import { api, ConflictRow, Pattern } from "../../lib/api";
import { dec, int, outOf, pct, sec } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_LABEL,
  ERROR_LABEL,
  TRAFFIC_BAND_LABEL,
  WEATHER_LABEL,
} from "../../lib/theme";

type Tab = "patterns" | "conflicts" | "search";
type Rank = "recurrence" | "ttc" | "scsi";

export default function ScenariosPage() {
  return (
    <RequireBatch>
      <ScenarioExplorer />
    </RequireBatch>
  );
}

function ScenarioExplorer() {
  const { batchId, batches, jobs, watchJob } = useApp();
  const router = useRouter();
  const [tab, setTab] = React.useState<Tab>("patterns");
  const [rank, setRank] = React.useState<Rank>("recurrence");

  const pat = useFetch(batchId ? () => api.patterns(batchId, 20) : null, [batchId]);
  const conflicts = useFetch(
    batchId
      ? () =>
          api.conflicts({
            batch_id: batchId,
            severity: "CRITICAL",
            order: "min_ttc",
            limit: 300,
          })
      : null,
    [batchId]
  );

  const ranked = React.useMemo(() => {
    const ps = pat.data?.patterns ?? [];
    const copy = [...ps];
    if (rank === "ttc") copy.sort((a, b) => a.median_min_ttc - b.median_min_ttc);
    else if (rank === "scsi") copy.sort((a, b) => b.mean_scsi - a.mean_scsi);
    else copy.sort((a, b) => b.occurrences - a.occurrences);
    return copy;
  }, [pat.data, rank]);

  return (
    <>
      <PageHeader
        title="Scenario explorer"
        lede="The output of the search: canonical situations that produced safety-critical conflicts, ranked by how many runs reproduced them."
      />

      <Tabs
        tabs={[
          { value: "patterns", label: "Recurring patterns", count: pat.data?.patterns.length },
          { value: "conflicts", label: "Critical conflicts", count: conflicts.data?.total },
          { value: "search", label: "Guided search" },
        ]}
        active={tab}
        onChange={setTab}
      />

      <div className="mt-3">
        {tab === "patterns" && (
          <>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <SegmentedControl
                label="Rank by"
                value={rank}
                onChange={setRank}
                options={[
                  {
                    value: "recurrence",
                    label: "Recurrence",
                    title: "Number of runs in which this pattern produced a qualifying conflict",
                  },
                  {
                    value: "ttc",
                    label: "Raw median TTC",
                    title: "Lowest median minimum time-to-collision first — a raw surrogate measure",
                  },
                  {
                    value: "scsi",
                    label: "Severity index",
                    title: "Mean constructed severity index — a presentation aid, not a validated measure",
                  },
                ]}
                size="sm"
              />
              {rank === "scsi" && (
                <Caveat>
                  The severity index is a constructed ranking aid. Ranking by raw median
                  TTC is the more defensible default.
                </Caveat>
              )}
            </div>

            {pat.loading && !pat.data ? (
              <div className="grid gap-2.5 lg:grid-cols-2">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} h={250} />
                ))}
              </div>
            ) : pat.error ? (
              <ErrorState error={pat.error} onRetry={pat.reload} />
            ) : ranked.length === 0 ? (
              <EmptyState
                title="No pattern met the recurrence threshold"
                body="A pattern must appear in at least two runs to be reported. Run more simulations so patterns can accumulate."
              />
            ) : (
              <>
                <Panel
                  title="Recurrence across the batch"
                  subtitle="How many runs each canonical situation appeared in."
                  className="mb-3"
                >
                  <HBarChart
                    data={ranked.slice(0, 14).map((p) => ({
                      key: p.id,
                      label: `${p.location} · ${WEATHER_LABEL[p.weather] ?? p.weather}`,
                      value: p.occurrences,
                      tip: [
                        { label: "Occurrences", value: outOf(p.occurrences, p.runs_evaluated) },
                        { label: "Traffic band", value: TRAFFIC_BAND_LABEL[p.traffic_band] ?? p.traffic_band },
                        { label: "Conflict type", value: CONFLICT_TYPE_LABEL[p.conflict_type] ?? p.conflict_type },
                        { label: "Median min TTC", value: sec(p.median_min_ttc) },
                        { label: "Median min PET", value: sec(p.median_min_pet) },
                        { label: "Evasive", value: pct(p.evasive_rate, 0) },
                        { label: "Contact", value: pct(p.collision_rate, 0) },
                      ],
                    }))}
                    labelWidth={214}
                    valueFormat={(v) => int(v)}
                  />
                  <Caveat>{pat.data?.interpretation}</Caveat>
                </Panel>

                <div className="grid gap-2.5 lg:grid-cols-2">
                  {ranked.map((p) => (
                    <PatternCard
                      key={p.id}
                      pattern={p}
                      onReplay={(runId) => router.push(`/replay?run=${runId}`)}
                    />
                  ))}
                </div>
              </>
            )}
          </>
        )}

        {tab === "conflicts" && (
          <Panel
            title="Critical conflicts in this batch"
            subtitle="Every conflict classified critical, lowest minimum TTC first."
            note={conflicts.data?.note}
          >
            {conflicts.loading && !conflicts.data ? (
              <Skeleton h={400} />
            ) : conflicts.error ? (
              <ErrorState error={conflicts.error} onRetry={conflicts.reload} />
            ) : conflicts.data ? (
              <DataTable<ConflictRow>
                rows={conflicts.data.conflicts}
                rowKey={(r, i) => `${r.run_id}-${i}`}
                onRowClick={(r) =>
                  r.has_replay ? router.push(`/replay?run=${r.run_id}`) : undefined
                }
                maxHeight={620}
                compact
                columns={[
                  {
                    key: "sev",
                    header: "Severity",
                    width: "92px",
                    render: (r) => <SeverityBadge severity={r.severity} />,
                  },
                  {
                    key: "ttc",
                    header: "Min TTC",
                    align: "right",
                    render: (r) => sec(r.min_ttc),
                    sortValue: (r) => r.min_ttc,
                  },
                  {
                    key: "pet",
                    header: "Min PET",
                    align: "right",
                    render: (r) => sec(r.min_pet),
                    sortValue: (r) => r.min_pet ?? 99,
                  },
                  {
                    key: "close",
                    header: "Closing",
                    align: "right",
                    render: (r) => dec(r.closing_speed, 1),
                    sortValue: (r) => r.closing_speed,
                    title: "Closing speed in m/s at the worst moment",
                  },
                  {
                    key: "g",
                    header: "Peak g",
                    align: "right",
                    render: (r) => dec(r.max_deceleration / 9.81, 1),
                    sortValue: (r) => r.max_deceleration,
                  },
                  { key: "loc", header: "Location", render: (r) => r.location },
                  {
                    key: "type",
                    header: "Type",
                    render: (r) => CONFLICT_TYPE_LABEL[r.conflict_type] ?? r.conflict_type,
                  },
                  {
                    key: "pair",
                    header: "Profiles",
                    render: (r) =>
                      `${ARCHETYPE_SHORT[r.archetype_a] ?? r.archetype_a} × ${
                        ARCHETYPE_SHORT[r.archetype_b] ?? r.archetype_b
                      }`,
                  },
                  {
                    key: "w",
                    header: "Weather",
                    render: (r) => WEATHER_LABEL[r.weather] ?? r.weather,
                  },
                  {
                    key: "dens",
                    header: "Density",
                    align: "right",
                    render: (r) => dec(r.traffic_density, 2),
                    sortValue: (r) => r.traffic_density,
                  },
                  {
                    key: "act",
                    header: "",
                    width: "62px",
                    render: (r) => (
                      <span className="flex gap-1">
                        {r.collision ? (
                          <Badge color="var(--critical)" glyph="✕">
                            hit
                          </Badge>
                        ) : r.evasive_action ? (
                          <Badge color="var(--warning)" glyph="△">
                            evaded
                          </Badge>
                        ) : null}
                      </span>
                    ),
                  },
                  {
                    key: "go",
                    header: "",
                    width: "24px",
                    render: (r) =>
                      r.has_replay ? (
                        <ArrowRight size={12} className="text-ink-3" aria-hidden />
                      ) : null,
                  },
                ]}
              />
            ) : null}
          </Panel>
        )}

        {tab === "search" && <GuidedSearchTab />}
      </div>
    </>
  );
}

/* ------------------------------------------------------------ guided tab --- */

function GuidedSearchTab() {
  const { batchId, batches, jobs, watchJob, setBatchId } = useApp();
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);

  const guidedBatches = batches.filter((b) => b.mode === "guided" && b.status === "complete");
  const mcBatches = batches.filter((b) => b.mode === "monte_carlo" && b.status === "complete");
  const [guidedId, setGuidedId] = React.useState<string | null>(null);
  const [randomId, setRandomId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!guidedId && guidedBatches.length) setGuidedId(guidedBatches[0].id);
    if (!randomId && mcBatches.length) setRandomId(mcBatches[0].id);
  }, [guidedBatches, mcBatches, guidedId, randomId]);

  const ov = useFetch(guidedId ? () => api.overview(guidedId) : null, [guidedId]);
  const cmp = useFetch(
    guidedId && randomId ? () => api.compareSearch(randomId, guidedId) : null,
    [guidedId, randomId]
  );

  const history = (ov.data?.summary?.history as
    | {
        generation: number;
        n_runs: number;
        best_objective: number;
        mean_objective: number;
        median_objective: number;
        critical_conflicts: number;
        collisions: number;
        distinct_patterns: number;
        elite_objective_mean: number;
      }[]
    | undefined) ?? [];

  const active = jobs.find((j) => j.status === "running");

  const launch = async () => {
    setBusy(true);
    setErr(null);
    try {
      const job = await api.startGuided({
        generations: 8,
        population: 80,
        elite_size: 12,
        seed_batch_id: batchId,
        label: "Guided scenario search",
      });
      watchJob(job);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-3">
      <Panel
        title="Adversarial scenario discovery"
        subtitle="Random search samples the space uniformly. Guided search keeps the scenarios that produced severe conflicts and mutates around them."
      >
        {err ? <ErrorState error={err} /> : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" onClick={launch} disabled={busy || !!active}>
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            {active ? "A search is already running" : "Run guided search (8 × 80)"}
          </Button>
          <span className="text-[11px] text-ink-3">
            Seeded from the elites of the currently selected batch.
          </span>
        </div>
        {active && <JobProgress job={active} />}
        <Caveat>
          The objective rewards severe, numerous simulated conflicts. It is a search
          objective — maximising it locates interesting regions of the parameter space
          and says nothing about real-world risk. Mutation redraws the random seed and
          elite selection keeps the best scenario per distinct signature, so the search
          cannot converge onto one lucky draw and report it as recurrence.
        </Caveat>
      </Panel>

      {guidedBatches.length === 0 ? (
        <EmptyState
          title="No guided search has been run yet"
          body="Run one above to compare it against the random baseline."
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1">
              <span className="label-xs">Guided batch</span>
              <select
                value={guidedId ?? ""}
                onChange={(e) => setGuidedId(e.target.value)}
                className="rounded border border-line-strong bg-surface-2 px-2 py-1 text-[11.5px] text-ink"
              >
                {guidedBatches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.label} · {int(b.n_runs_completed)} runs
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="label-xs">Random baseline</span>
              <select
                value={randomId ?? ""}
                onChange={(e) => setRandomId(e.target.value)}
                className="rounded border border-line-strong bg-surface-2 px-2 py-1 text-[11.5px] text-ink"
              >
                {mcBatches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.label} · {int(b.n_runs_completed)} runs
                  </option>
                ))}
              </select>
            </label>
            {guidedId && (
              <Button size="sm" className="self-end" onClick={() => setBatchId(guidedId)}>
                Analyse this guided batch
              </Button>
            )}
          </div>

          {history.length > 0 && (
            <Panel
              title="Search convergence"
              subtitle="Objective value by generation. A rising mean means the search is concentrating on severe regions."
            >
              <LineChart
                series={[
                  {
                    key: "best",
                    label: "Best in generation",
                    color: "var(--series-2)",
                    points: history.map((h) => ({ x: h.generation, y: h.best_objective })),
                  },
                  {
                    key: "mean",
                    label: "Generation mean",
                    color: "var(--series-1)",
                    points: history.map((h) => ({ x: h.generation, y: h.mean_objective })),
                  },
                  {
                    key: "elite",
                    label: "Elite set mean",
                    color: "var(--series-3)",
                    points: history.map((h) => ({ x: h.generation, y: h.elite_objective_mean })),
                    dashed: true,
                  },
                ]}
                height={200}
                xLabel="generation"
                yLabel="search objective"
                xFormat={(v) => v.toFixed(0)}
                yFormat={(v) => v.toFixed(3)}
                markers
              />
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-2.5 sm:grid-cols-4">
                <Metric label="Generations" value={int(history.length)} />
                <Metric
                  label="First-gen mean"
                  value={dec(history[0]?.mean_objective, 4)}
                />
                <Metric
                  label="Last-gen mean"
                  value={dec(history[history.length - 1]?.mean_objective, 4)}
                />
                <Metric
                  label="Best found"
                  value={dec(Math.max(...history.map((h) => h.best_objective)), 4)}
                />
              </div>
              <Caveat>
                {String(ov.data?.summary?.objective_definition ?? "")}
              </Caveat>
            </Panel>
          )}

          {cmp.data && cmp.data.random && cmp.data.guided && (
            <Panel
              title="Guided search against random search"
              subtitle="Experiment 9: does directed search find severe simulated scenarios more efficiently?"
              note={String(cmp.data.delta?.note ?? "")}
            >
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr>
                      <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-left">
                        Measure
                      </th>
                      <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-right">
                        Random
                      </th>
                      <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-right">
                        Guided
                      </th>
                      <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-right">
                        Ratio
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["runs", "Runs", 0],
                      ["critical_per_run", "Critical conflicts per run", 3],
                      ["fraction_runs_with_critical", "Fraction of runs with a critical conflict", 3],
                      ["mean_peak_scsi", "Mean peak severity index", 4],
                      ["lowest_min_ttc", "Lowest minimum TTC (s)", 3],
                      ["mean_objective", "Mean search objective", 4],
                      ["p90_objective", "90th percentile objective", 4],
                      ["collisions", "Collisions", 0],
                    ].map(([key, label, digits]) => {
                      const r = Number(cmp.data!.random[key as string]);
                      const g = Number(cmp.data!.guided[key as string]);
                      const ratio = r ? g / r : null;
                      return (
                        <tr key={String(key)} className="border-b border-line/60">
                          <td className="px-2 py-1.5 text-ink-2">{label}</td>
                          <td className="num px-2 py-1.5 text-right text-ink">
                            {dec(r, Number(digits))}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink">
                            {dec(g, Number(digits))}
                          </td>
                          <td className="num px-2 py-1.5 text-right text-ink-3">
                            {ratio === null ? "—" : `${dec(ratio, 2)}×`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
