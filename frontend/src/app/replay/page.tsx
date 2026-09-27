"use client";

import { useRouter, useSearchParams } from "next/navigation";
import React, { Suspense } from "react";

import { ReplayViewer } from "../../components/ReplayViewer";
import {
  Metric,
  PageHeader,
  RequireBatch,
  SeverityBadge,
} from "../../components/Common";
import {
  Badge,
  Caveat,
  DataTable,
  EmptyState,
  ErrorState,
  KeyValue,
  Loading,
  Panel,
  Skeleton,
} from "../../components/ui";
import { api, RunRow } from "../../lib/api";
import { dec, int, pct, sec, titleCase } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_LABEL,
  DECISION_LABEL,
  ERROR_LABEL,
  SEVERITY,
  WEATHER_LABEL,
} from "../../lib/theme";

export default function ReplayPage() {
  return (
    <RequireBatch>
      <Suspense fallback={<Loading label="Loading replay" />}>
        <ReplayScreen />
      </Suspense>
    </RequireBatch>
  );
}

function ReplayScreen() {
  const { batchId, track, meta } = useApp();
  const params = useSearchParams();
  const router = useRouter();
  const runFromUrl = params.get("run");

  const replayable = useFetch(
    batchId
      ? () =>
          api.runs({
            batch_id: batchId,
            has_replay: true,
            order: "min_ttc",
            direction: "asc",
            limit: 60,
          })
      : null,
    [batchId]
  );

  const runId = runFromUrl ?? replayable.data?.runs[0]?.id ?? null;

  const replay = useFetch(runId ? () => api.replay(runId) : null, [runId]);
  const explain = useFetch(runId ? () => api.explain(runId) : null, [runId]);

  const select = (id: string) => router.push(`/replay?run=${id}`);

  const thresholds = meta?.thresholds ?? {};

  return (
    <>
      <PageHeader
        title="Incident replay"
        lede="Watch a recorded conflict develop, then read the causal chain reconstructed from the trajectory that produced it. Replay windows are stored only for the most severe runs in a batch."
        right={
          runId && (
            <span className="num text-[11px] text-ink-3">run {runId.slice(0, 10)}</span>
          )
        }
      />

      <div className="mb-3">
        <Panel
          title="Replayable runs"
          subtitle="Lowest minimum TTC first. Select one to load it."
          dense
        >
          {replayable.loading && !replayable.data ? (
            <Skeleton h={120} />
          ) : replayable.error ? (
            <ErrorState error={replayable.error} onRetry={replayable.reload} />
          ) : replayable.data && replayable.data.runs.length > 0 ? (
            <DataTable<RunRow>
              rows={replayable.data.runs}
              rowKey={(r) => r.id}
              selectedKey={runId ?? undefined}
              onRowClick={(r) => select(r.id)}
              maxHeight={148}
              compact
              columns={[
                {
                  key: "ttc",
                  header: "Min TTC",
                  align: "right",
                  width: "72px",
                  render: (r) => sec(r.min_ttc),
                  sortValue: (r) => r.min_ttc ?? 99,
                },
                {
                  key: "pet",
                  header: "Min PET",
                  align: "right",
                  width: "72px",
                  render: (r) => sec(r.min_pet),
                },
                {
                  key: "w",
                  header: "Weather",
                  render: (r) => WEATHER_LABEL[r.weather] ?? r.weather,
                },
                { key: "cars", header: "Cars", align: "right", render: (r) => int(r.n_cars) },
                {
                  key: "dens",
                  header: "Density",
                  align: "right",
                  render: (r) => dec(r.traffic_density_measured, 2),
                },
                {
                  key: "crit",
                  header: "Critical",
                  align: "right",
                  render: (r) => int(r.n_critical),
                  sortValue: (r) => r.n_critical,
                },
                {
                  key: "out",
                  header: "Outcome",
                  render: (r) => (
                    <span className="flex gap-1">
                      {r.n_collisions > 0 && (
                        <Badge color={SEVERITY.INCIDENT.color} glyph={SEVERITY.INCIDENT.glyph}>
                          contact
                        </Badge>
                      )}
                      {r.n_spins > 0 && <Badge>spin</Badge>}
                      {r.n_off_track > 0 && <Badge>off track</Badge>}
                      {r.n_collisions === 0 && r.n_spins === 0 && r.n_off_track === 0 && (
                        <Badge color={SEVERITY.WARNING.color} glyph={SEVERITY.WARNING.glyph}>
                          near miss
                        </Badge>
                      )}
                    </span>
                  ),
                },
                {
                  key: "err",
                  header: "Dominant error",
                  render: (r) =>
                    r.dominant_error ? ERROR_LABEL[r.dominant_error] ?? r.dominant_error : "—",
                },
                { key: "seed", header: "Seed", align: "right", render: (r) => int(r.seed) },
              ]}
            />
          ) : (
            <EmptyState
              title="No replay windows in this batch"
              body="Replays are retained only for the runs with the lowest minimum TTC or with contact. Run a batch with a replay budget above zero."
            />
          )}
        </Panel>
      </div>

      {!runId ? null : replay.loading && !replay.data ? (
        <Skeleton h={420} />
      ) : replay.error ? (
        <ErrorState error={replay.error} onRetry={replay.reload} />
      ) : replay.data && track ? (
        <>
          <ReplayViewer
            replay={replay.data}
            track={track}
            ttcThreshold={thresholds.ttc_conflict ?? 1.5}
            criticalThreshold={thresholds.ttc_critical ?? 0.8}
          />

          {/* ------------------------------------------- why did this happen --- */}
          <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
            <Panel
              title="Why did this happen?"
              subtitle="Reconstructed from the recorded trajectory, errors and decisions — not from the outcome."
              note={explain.data?.caveat}
            >
              {explain.loading && !explain.data ? (
                <Skeleton h={260} />
              ) : explain.error ? (
                <ErrorState error={explain.error} onRetry={explain.reload} />
              ) : explain.data ? (
                <>
                  <p className="text-[12.5px] leading-relaxed text-ink">
                    {explain.data.narrative}
                  </p>

                  <div className="mt-3 border-t border-line pt-3">
                    <p className="label-xs mb-2">Event chain</p>
                    <ol className="relative space-y-2 pl-4">
                      <span
                        className="absolute left-[3px] top-1 bottom-1 w-[1px]"
                        style={{ background: "var(--border-strong)" }}
                        aria-hidden
                      />
                      {explain.data.event_chain.map((c, i) => (
                        <li key={i} className="relative">
                          <span
                            className="absolute left-[-13px] top-[5px] h-[7px] w-[7px] rounded-full border"
                            style={{
                              background: chainColor(c.kind),
                              borderColor: "var(--surface-1)",
                            }}
                            aria-hidden
                          />
                          <div className="flex flex-wrap items-baseline gap-x-2">
                            <span className="num text-[10.5px] text-ink-3">
                              {c.t === null ? "setup" : `${dec(c.t, 2)}s`}
                            </span>
                            <span
                              className="text-[9.5px] font-semibold uppercase tracking-wider"
                              style={{ color: chainColor(c.kind) }}
                            >
                              {c.kind}
                            </span>
                          </div>
                          <p className="mt-0.5 text-[12px] leading-snug text-ink-2">{c.text}</p>
                        </li>
                      ))}
                    </ol>
                  </div>
                </>
              ) : null}
            </Panel>

            <div className="flex min-w-0 flex-col gap-3">
              {explain.data?.conflict && (
                <Panel title="Measured surrogate metrics" dense>
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    <SeverityBadge severity={explain.data.conflict.severity} />
                    <Badge>
                      {CONFLICT_TYPE_LABEL[explain.data.conflict.conflict_type] ??
                        explain.data.conflict.conflict_type}
                    </Badge>
                    <Badge>{explain.data.conflict.location}</Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                    <Metric label="Minimum TTC" value={sec(explain.data.metrics.min_ttc)} />
                    <Metric label="Minimum PET" value={sec(explain.data.metrics.min_pet)} />
                    <Metric
                      label="Closing speed"
                      value={`${dec(explain.data.metrics.closing_speed, 1)} m/s`}
                    />
                    <Metric
                      label="Peak decel"
                      value={`${dec(explain.data.metrics.max_deceleration_g, 1)} g`}
                    />
                    <Metric
                      label="Evasive action"
                      value={explain.data.metrics.evasive_action ? "yes" : "no"}
                    />
                    <Metric
                      label="Contact"
                      value={explain.data.metrics.collision ? "yes" : "no"}
                    />
                  </div>

                  <div className="mt-3 border-t border-line pt-2.5">
                    <p className="label-xs mb-1.5">
                      Conflict severity index — how it was constructed
                    </p>
                    <ul className="space-y-1">
                      {Object.entries(explain.data.metrics.scsi_breakdown.contributions).map(
                        ([k, v]) => {
                          const term = explain.data!.metrics.scsi_breakdown.terms[k];
                          const weight = explain.data!.metrics.scsi_breakdown.weights[k];
                          const total = explain.data!.metrics.scsi_breakdown.total || 1;
                          return (
                            <li key={k}>
                              <div className="flex items-baseline justify-between gap-2">
                                <span className="text-[11px] text-ink-2">
                                  {titleCase(k)}{" "}
                                  <span className="num text-ink-3">
                                    {dec(term, 2)} × {dec(weight, 2)}
                                  </span>
                                </span>
                                <span className="num text-[11px] text-ink">{dec(v, 3)}</span>
                              </div>
                              <div className="mt-0.5 h-[3px] overflow-hidden rounded-full bg-surface-3">
                                <div
                                  className="h-full rounded-full"
                                  style={{
                                    width: `${(v / total) * 100}%`,
                                    background: "var(--series-1)",
                                  }}
                                />
                              </div>
                            </li>
                          );
                        }
                      )}
                    </ul>
                    <div className="mt-1.5 flex items-baseline justify-between border-t border-line pt-1.5">
                      <span className="text-[11px] text-ink-2">Total SCSI</span>
                      <span className="num text-[12.5px] text-ink">
                        {dec(explain.data.metrics.scsi_breakdown.total, 3)}
                      </span>
                    </div>
                    <Caveat>
                      A constructed ranking aid, not a validated severity measure and not a
                      probability. Raw metrics above are the primary record.
                    </Caveat>
                  </div>
                </Panel>
              )}

              {explain.data && (
                <Panel
                  title="Root conditions"
                  subtitle="The configured inputs this run was drawn with."
                >
                  {groupBy(explain.data.root_conditions, (r) => r.group).map(
                    ([group, rows]) => (
                      <div key={group} className="mb-3 last:mb-0">
                        <p className="label-xs mb-1.5">{group}</p>
                        <dl className="space-y-1">
                          {rows.map((r, i) => (
                            <div key={i}>
                              <div className="flex items-baseline justify-between gap-2">
                                <dt className="text-[11.5px] text-ink-3">{r.label}</dt>
                                <dd className="num text-[11.5px] text-ink">{String(r.value)}</dd>
                              </div>
                              {r.detail && (
                                <p className="mt-0.5 text-[10px] leading-snug text-ink-3">
                                  {r.detail}
                                </p>
                              )}
                            </div>
                          ))}
                        </dl>
                      </div>
                    )
                  )}
                </Panel>
              )}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}

function chainColor(kind: string): string {
  switch (kind) {
    case "condition":
      return "var(--series-1)";
    case "mechanism":
      return "var(--series-3)";
    case "error":
      return "var(--warning)";
    case "intent":
      return "var(--series-7)";
    case "approach":
      return "var(--series-4)";
    case "state":
      return "var(--text-secondary)";
    case "response":
      return "var(--serious)";
    case "critical":
      return "var(--critical)";
    case "outcome":
      return "var(--text-primary)";
    default:
      return "var(--text-muted)";
  }
}

function groupBy<T>(rows: T[], key: (r: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  for (const r of rows) {
    const k = key(r);
    if (!m.has(k)) m.set(k, []);
    m.get(k)!.push(r);
  }
  return [...m.entries()];
}
