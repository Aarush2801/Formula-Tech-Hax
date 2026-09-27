"use client";

import { Check, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import React from "react";

import { HBarChart } from "../../components/charts";
import { Metric, PageHeader, SeverityBadge } from "../../components/Common";
import {
  Badge,
  Button,
  Caveat,
  DataTable,
  EmptyState,
  ErrorState,
  Panel,
  Skeleton,
  Tabs,
} from "../../components/ui";
import { api, BatchRow, RunRow } from "../../lib/api";
import { datetime, dec, int, ms, pct, sec } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import { ERROR_LABEL, SEVERITY, WEATHER_LABEL } from "../../lib/theme";

type Tab = "batches" | "runs";

export default function HistoryPage() {
  const { batches, batchId, setBatchId, refreshBatches, apiOnline, metaError } = useApp();
  const router = useRouter();
  const [tab, setTab] = React.useState<Tab>("batches");
  const [compare, setCompare] = React.useState<string[]>([]);
  const [deleting, setDeleting] = React.useState<string | null>(null);

  const runs = useFetch(
    batchId && tab === "runs"
      ? () =>
          api.runs({
            batch_id: batchId,
            order: "peak_scsi",
            direction: "desc",
            limit: 250,
          })
      : null,
    [batchId, tab]
  );

  const toggleCompare = (id: string) =>
    setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-4)));

  const del = async (id: string) => {
    setDeleting(id);
    try {
      await api.deleteBatch(id);
      await refreshBatches();
      setCompare((c) => c.filter((x) => x !== id));
    } finally {
      setDeleting(null);
    }
  };

  if (apiOnline === false) {
    return (
      <>
        <PageHeader title="Simulation history" />
        <ErrorState error={metaError ?? new Error("API unreachable")} />
      </>
    );
  }

  const compared = batches.filter((b) => compare.includes(b.id));

  return (
    <>
      <PageHeader
        title="Simulation history"
        lede="Every batch that has been executed, with the configuration needed to reproduce it. A batch is fully determined by its seed base, run count and scenario space."
      />

      <Tabs
        tabs={[
          { value: "batches", label: "Batches", count: batches.length },
          { value: "runs", label: "Runs in selected batch" },
        ]}
        active={tab}
        onChange={setTab}
      />

      <div className="mt-3">
        {tab === "batches" ? (
          batches.length === 0 ? (
            <EmptyState
              title="No batches yet"
              body="Run a stress test from the Overview screen."
            />
          ) : (
            <>
              <Panel
                title="Batches"
                subtitle="Click a row to analyse it. Tick up to four to compare."
                note="Counts are simulated outcomes under each batch's own assumptions; batches with different scenario spaces are not directly comparable."
              >
                <DataTable<BatchRow>
                  rows={batches}
                  rowKey={(r) => r.id}
                  selectedKey={batchId ?? undefined}
                  onRowClick={(r) =>
                    r.status === "complete" && r.n_runs_completed > 0
                      ? setBatchId(r.id)
                      : undefined
                  }
                  maxHeight={520}
                  compact
                  columns={[
                    {
                      key: "cmp",
                      header: "",
                      width: "26px",
                      render: (r) => (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCompare(r.id);
                          }}
                          aria-label={`Compare ${r.label}`}
                          className={`flex h-[14px] w-[14px] items-center justify-center rounded border ${
                            compare.includes(r.id)
                              ? "border-[color:var(--accent)] bg-[color:var(--accent)]/25"
                              : "border-line-strong"
                          }`}
                        >
                          {compare.includes(r.id) && (
                            <Check size={9} style={{ color: "var(--accent)" }} />
                          )}
                        </button>
                      ),
                    },
                    {
                      key: "label",
                      header: "Batch",
                      render: (r) => (
                        <span>
                          <span className="flex items-center gap-1.5">
                            {batchId === r.id && (
                              <span
                                className="h-[5px] w-[5px] rounded-full"
                                style={{ background: "var(--accent)" }}
                                aria-hidden
                              />
                            )}
                            <span className="text-[12px] text-ink">{r.label || r.id}</span>
                          </span>
                          <span className="num block text-[9.5px] text-ink-3">{r.id}</span>
                        </span>
                      ),
                      sortValue: (r) => r.label,
                    },
                    { key: "mode", header: "Mode", render: (r) => <Badge>{r.mode}</Badge> },
                    {
                      key: "status",
                      header: "Status",
                      render: (r) =>
                        r.status === "complete" ? (
                          <Badge color="var(--good)" glyph="✓">
                            complete
                          </Badge>
                        ) : (
                          <Badge color="var(--warning)" glyph="△">
                            {r.status}
                          </Badge>
                        ),
                    },
                    {
                      key: "runs",
                      header: "Runs",
                      align: "right",
                      render: (r) => int(r.n_runs_completed),
                      sortValue: (r) => r.n_runs_completed,
                    },
                    { key: "seed", header: "Seed base", align: "right", render: (r) => int(r.seed_base) },
                    {
                      key: "cars",
                      header: "Mean cars",
                      align: "right",
                      render: (r) => dec(r.avg_cars, 1),
                    },
                    {
                      key: "conf",
                      header: "Conflicts",
                      align: "right",
                      render: (r) => int(r.conflicts),
                      sortValue: (r) => r.conflicts ?? 0,
                    },
                    {
                      key: "crit",
                      header: "Critical",
                      align: "right",
                      render: (r) => int(r.critical),
                      sortValue: (r) => r.critical ?? 0,
                    },
                    {
                      key: "coll",
                      header: "Contacts",
                      align: "right",
                      render: (r) => int(r.collisions),
                      sortValue: (r) => r.collisions ?? 0,
                    },
                    {
                      key: "ttc",
                      header: "Mean min TTC",
                      align: "right",
                      render: (r) => dec(r.avg_min_ttc, 3),
                      sortValue: (r) => r.avg_min_ttc ?? 99,
                    },
                    {
                      key: "pet",
                      header: "Mean min PET",
                      align: "right",
                      render: (r) => dec(r.avg_min_pet, 3),
                    },
                    {
                      key: "wall",
                      header: "Wall time",
                      align: "right",
                      render: (r) => ms(r.wall_time_ms),
                      sortValue: (r) => r.wall_time_ms ?? 0,
                    },
                    {
                      key: "when",
                      header: "Created",
                      render: (r) => datetime(r.created_at),
                      sortValue: (r) => r.created_at,
                    },
                    {
                      key: "del",
                      header: "",
                      width: "28px",
                      render: (r) => (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (
                              window.confirm(
                                `Delete batch "${r.label || r.id}" and all ${int(
                                  r.n_runs_completed
                                )} of its runs, conflicts, events and replays? This cannot be undone.`
                              )
                            )
                              del(r.id);
                          }}
                          disabled={deleting === r.id}
                          aria-label={`Delete ${r.label}`}
                          className="text-ink-3 hover:text-[color:var(--critical)] disabled:opacity-40"
                        >
                          <Trash2 size={12} />
                        </button>
                      ),
                    },
                  ]}
                />
              </Panel>

              {compared.length >= 2 && (
                <div className="mt-3">
                  <Panel
                    title="Compare batches"
                    subtitle={`${compared.length} selected. Per-run rates, so batches of different sizes can be set side by side.`}
                  >
                    <div className="overflow-x-auto">
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr>
                            <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-left">
                              Measure
                            </th>
                            {compared.map((b) => (
                              <th
                                key={b.id}
                                className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-right"
                              >
                                {b.label || b.id}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {[
                            ["Runs", (b: BatchRow) => int(b.n_runs_completed)],
                            ["Mode", (b: BatchRow) => b.mode],
                            ["Seed base", (b: BatchRow) => int(b.seed_base)],
                            ["Mean field size", (b: BatchRow) => dec(b.avg_cars, 1)],
                            [
                              "Conflicts per run",
                              (b: BatchRow) =>
                                dec((b.conflicts ?? 0) / Math.max(b.n_runs_completed, 1), 3),
                            ],
                            [
                              "Critical per run",
                              (b: BatchRow) =>
                                dec((b.critical ?? 0) / Math.max(b.n_runs_completed, 1), 3),
                            ],
                            [
                              "Near misses per run",
                              (b: BatchRow) =>
                                dec((b.near_misses ?? 0) / Math.max(b.n_runs_completed, 1), 3),
                            ],
                            [
                              "Contacts per run",
                              (b: BatchRow) =>
                                dec((b.collisions ?? 0) / Math.max(b.n_runs_completed, 1), 4),
                            ],
                            ["Mean min TTC", (b: BatchRow) => dec(b.avg_min_ttc, 3)],
                            ["Lowest min TTC", (b: BatchRow) => dec(b.lowest_min_ttc, 3)],
                            ["Mean min PET", (b: BatchRow) => dec(b.avg_min_pet, 3)],
                            ["Wall time", (b: BatchRow) => ms(b.wall_time_ms)],
                            [
                              "Runs per second",
                              (b: BatchRow) =>
                                b.wall_time_ms
                                  ? dec(b.n_runs_completed / (b.wall_time_ms / 1000), 1)
                                  : "—",
                            ],
                          ].map(([label, fn]) => (
                            <tr key={String(label)} className="border-b border-line/60">
                              <td className="px-2 py-1.5 text-ink-2">{String(label)}</td>
                              {compared.map((b) => (
                                <td key={b.id} className="num px-2 py-1.5 text-right text-ink">
                                  {(fn as (b: BatchRow) => string)(b)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Caveat>
                      Two batches are comparable only if they searched the same scenario
                      space. A guided batch concentrates on severe regions by design, so
                      its higher rates reflect where it chose to sample, not a different
                      world.
                    </Caveat>
                  </Panel>
                </div>
              )}
            </>
          )
        ) : (
          <Panel
            title="Runs"
            subtitle="Ranked by peak severity index. Click a run with a stored replay to open it."
            note={runs.data?.note}
          >
            {runs.loading && !runs.data ? (
              <Skeleton h={480} />
            ) : runs.error ? (
              <ErrorState error={runs.error} onRetry={runs.reload} />
            ) : runs.data ? (
              <DataTable<RunRow>
                rows={runs.data.runs}
                rowKey={(r) => r.id}
                onRowClick={(r) => (r.has_replay ? router.push(`/replay?run=${r.id}`) : undefined)}
                maxHeight={620}
                compact
                columns={[
                  { key: "seed", header: "Seed", align: "right", render: (r) => int(r.seed), sortValue: (r) => r.seed },
                  { key: "w", header: "Weather", render: (r) => WEATHER_LABEL[r.weather] ?? r.weather },
                  { key: "cars", header: "Cars", align: "right", render: (r) => int(r.n_cars), sortValue: (r) => r.n_cars },
                  {
                    key: "dens",
                    header: "Density",
                    align: "right",
                    render: (r) => dec(r.traffic_density_measured, 2),
                    sortValue: (r) => r.traffic_density_measured,
                    title: "Measured, not requested",
                  },
                  { key: "grip", header: "Grip", align: "right", render: (r) => dec(r.grip, 2), sortValue: (r) => r.grip },
                  {
                    key: "width",
                    header: "Width ×",
                    align: "right",
                    render: (r) => dec(r.track_width_multiplier, 2),
                  },
                  {
                    key: "err",
                    header: "Error ×",
                    align: "right",
                    render: (r) => dec(r.error_rate_multiplier, 2),
                  },
                  { key: "conf", header: "Conf", align: "right", render: (r) => int(r.n_conflicts), sortValue: (r) => r.n_conflicts },
                  { key: "crit", header: "Crit", align: "right", render: (r) => int(r.n_critical), sortValue: (r) => r.n_critical },
                  { key: "ttc", header: "Min TTC", align: "right", render: (r) => sec(r.min_ttc), sortValue: (r) => r.min_ttc ?? 99 },
                  { key: "pet", header: "Min PET", align: "right", render: (r) => sec(r.min_pet) },
                  {
                    key: "g",
                    header: "Peak g",
                    align: "right",
                    render: (r) => dec(r.max_deceleration / 9.81, 1),
                    sortValue: (r) => r.max_deceleration,
                  },
                  {
                    key: "out",
                    header: "Outcome",
                    render: (r) => (
                      <span className="flex gap-1">
                        {r.n_collisions > 0 && (
                          <Badge color={SEVERITY.INCIDENT.color} glyph={SEVERITY.INCIDENT.glyph}>
                            {int(r.n_collisions)}
                          </Badge>
                        )}
                        {r.n_spins > 0 && <Badge>{int(r.n_spins)} spin</Badge>}
                        {r.n_off_track > 0 && <Badge>{int(r.n_off_track)} off</Badge>}
                      </span>
                    ),
                  },
                  {
                    key: "derr",
                    header: "Dominant error",
                    render: (r) =>
                      r.dominant_error ? ERROR_LABEL[r.dominant_error] ?? r.dominant_error : "—",
                  },
                  {
                    key: "scsi",
                    header: "SCSI",
                    align: "right",
                    render: (r) => dec(r.peak_scsi, 3),
                    sortValue: (r) => r.peak_scsi,
                    title: "Constructed ranking index — see Model Assumptions",
                  },
                  {
                    key: "rep",
                    header: "",
                    width: "24px",
                    render: (r) =>
                      r.has_replay ? (
                        <span className="text-[10px]" style={{ color: "var(--accent)" }}>
                          ▶
                        </span>
                      ) : null,
                  },
                ]}
              />
            ) : null}
          </Panel>
        )}
      </div>
    </>
  );
}
