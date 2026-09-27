"use client";

import { ArrowRight, Layers } from "lucide-react";
import Link from "next/link";
import React from "react";

import { BarChart, HBarChart, Legend, RampLegend } from "../components/charts";
import { CircuitMap } from "../components/CircuitMap";
import {
  AskPanel,
  Metric,
  PageHeader,
  PatternCard,
  StressTestLauncher,
} from "../components/Common";
import {
  Button,
  Caveat,
  ErrorState,
  Loading,
  Panel,
  Skeleton,
  StatTile,
} from "../components/ui";
import { api } from "../lib/api";
import { dec, int, ms, pct, sec } from "../lib/format";
import { useApp, useFetch } from "../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_LABEL,
  SEVERITY,
  WEATHER_COLOR,
  WEATHER_LABEL,
  WEATHER_ORDER,
} from "../lib/theme";

export default function OverviewPage() {
  const { batchId, batch, track, meta, apiOnline, metaError } = useApp();

  const ov = useFetch(batchId ? () => api.overview(batchId) : null, [batchId]);
  const hs = useFetch(batchId ? () => api.hotspots(batchId) : null, [batchId]);
  const pat = useFetch(batchId ? () => api.patterns(batchId, 20) : null, [batchId]);
  const env = useFetch(batchId ? () => api.environment(batchId) : null, [batchId]);
  const im = useFetch(batchId ? () => api.interactions(batchId) : null, [batchId]);
  const cb = useFetch(batchId ? () => api.conflictBreakdown(batchId) : null, [batchId]);

  const t = ov.data?.totals ?? {};

  if (apiOnline === false) {
    return (
      <>
        <PageHeader title="APEX Safety Stress Test" />
        <ErrorState error={metaError ?? new Error("API unreachable")} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="APEX Safety Stress Test"
        lede={
          meta?.positioning ??
          "An automated scenario-generation and safety-stress-testing layer above a simulator."
        }
        right={
          batch && (
            <div className="text-right">
              <div className="num text-[13px] text-ink">{int(batch.n_runs_completed)} runs</div>
              <div className="text-[10px] text-ink-3">
                seed base {batch.seed_base} · {ms(batch.wall_time_ms)}
              </div>
            </div>
          )
        }
      />

      {/* ------------------------------------------------ headline metrics --- */}
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
        {ov.loading && !ov.data ? (
          Array.from({ length: 6 }, (_, i) => <Skeleton key={i} h={84} />)
        ) : (
          <>
            <StatTile
              label="Simulations"
              value={int(t.runs as number)}
              sub={`${int(t.total_timesteps as number)} timesteps simulated`}
              hint="Number of independent scenario runs executed in this batch."
            />
            <StatTile
              label="Driver agents"
              value={dec(t.avg_cars as number, 1)}
              unit="mean"
              sub={`up to ${meta?.default_space ? 22 : 22} per run`}
              hint="Mean field size across the batch. Field size is one of the sampled dimensions."
            />
            <StatTile
              label="Critical conflicts"
              value={int(t.critical as number)}
              tone="serious"
              glyph={SEVERITY.CRITICAL.glyph}
              sub={`in ${pct(ov.data?.fraction_runs_with_critical ?? 0, 1)} of runs`}
              hint={SEVERITY.CRITICAL.description}
            />
            <StatTile
              label="Near misses"
              value={int(t.near_misses as number)}
              tone="warning"
              glyph={SEVERITY.WARNING.glyph}
              sub="evasive action, no contact"
              hint="A conflict that crossed the surrogate-safety filter, involved an evasive manoeuvre and did not end in contact."
            />
            <StatTile
              label="Collisions"
              value={int(t.collisions as number)}
              tone="critical"
              glyph={SEVERITY.INCIDENT.glyph}
              sub={`+ ${int(t.light_contacts as number)} light contacts`}
              hint="Contact above the collision-energy threshold. Lighter wheel-to-wheel contact is counted separately."
            />
            <StatTile
              label="Mean min TTC"
              value={dec(t.avg_min_ttc as number, 2)}
              unit="s"
              sub={`lowest ${sec(t.lowest_min_ttc as number)}`}
              hint="Mean, across runs that produced a conflict, of that run's minimum time-to-collision."
            />
          </>
        )}
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        {/* -------------------------------------------- safety hotspots --- */}
        <Panel
          title="Safety hotspots"
          subtitle="Conflicts located on the circuit. Tint is conflict count, on a single-hue scale."
          right={
            <Link href="/circuit">
              <Button size="sm" variant="ghost">
                Circuit analysis <ArrowRight size={11} />
              </Button>
            </Link>
          }
          note={hs.data?.note}
        >
          {hs.loading && !hs.data ? (
            <Skeleton h={330} />
          ) : hs.error ? (
            <ErrorState error={hs.error} onRetry={hs.reload} />
          ) : hs.data && track ? (
            <>
              <CircuitMap
                track={track}
                height={330}
                segmentValues={Object.fromEntries(
                  hs.data.segments.map((s) => [s.segment_index, s.conflicts])
                )}
              />
              <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
                <RampLegend
                  max={Math.max(...hs.data.segments.map((s) => s.conflicts), 0)}
                  label="conflicts in segment"
                  format={(v) => int(v)}
                />
                <span className="num text-[10.5px] text-ink-3">
                  {int(hs.data.total_conflicts)} conflicts · {int(hs.data.n_runs)} runs
                </span>
              </div>
            </>
          ) : (
            <Loading />
          )}
        </Panel>

        {/* ---------------------------------------------- top locations --- */}
        <div className="flex flex-col gap-3">
          <Panel
            title="Most flagged locations"
            subtitle="Conflicts per run, by track segment."
          >
            {hs.data ? (
              <HBarChart
                data={hs.data.top_segments.slice(0, 8).map((s) => ({
                  key: String(s.segment_index),
                  label: s.name,
                  value: s.conflicts_per_run,
                  tip: [
                    { label: "Conflicts", value: int(s.conflicts) },
                    { label: "Per run", value: dec(s.conflicts_per_run, 3) },
                    { label: "Critical", value: int(s.critical) },
                    { label: "Contacts", value: int(s.collisions) },
                    { label: "Median min TTC", value: sec(s.median_min_ttc) },
                    { label: "Width", value: `${dec(s.width, 1)} m` },
                  ],
                }))}
                labelWidth={158}
                valueFormat={(v) => dec(v, 3)}
              />
            ) : (
              <Skeleton h={180} />
            )}
          </Panel>

          <Panel
            title="Per-run minimum TTC"
            subtitle="How close the closest interaction came, per run."
          >
            {ov.data ? (
              <BarChart
                data={ov.data.min_ttc_distribution.map((d, i) => ({
                  key: d.label,
                  label: d.label,
                  value: d.count,
                  color: `var(--seq-${Math.min(7, 7 - i)})`,
                  tip: [
                    { label: "Runs", value: int(d.count) },
                    { label: "Share of runs with a conflict", value: pct(d.fraction, 1) },
                  ],
                }))}
                height={150}
                yLabel="runs"
                valueFormat={(v) => int(v)}
              />
            ) : (
              <Skeleton h={150} />
            )}
          </Panel>
        </div>
      </div>

      {/* -------------------------------------------------- top scenarios --- */}
      <div className="mt-3">
        <Panel
          title="Top recurring critical scenarios"
          subtitle="Canonical situations that produced qualifying conflicts in the most runs."
          right={
            <Link href="/scenarios">
              <Button size="sm" variant="ghost">
                Scenario explorer <ArrowRight size={11} />
              </Button>
            </Link>
          }
          note={pat.data?.interpretation}
        >
          {pat.loading && !pat.data ? (
            <Skeleton h={220} />
          ) : pat.error ? (
            <ErrorState error={pat.error} onRetry={pat.reload} />
          ) : pat.data && pat.data.patterns.length > 0 ? (
            <div className="grid gap-2.5 lg:grid-cols-2">
              {pat.data.patterns.slice(0, 4).map((p) => (
                <PatternCard key={p.id} pattern={p} />
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-[12px] text-ink-3">
              No pattern met the minimum recurrence threshold in this batch. Run more
              simulations to let patterns accumulate.
            </p>
          )}
        </Panel>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        {/* -------------------------------------------- environmental --- */}
        <Panel
          title="Environmental effects"
          subtitle="Per-run outcome rates by condition."
          right={
            <Link href="/environment">
              <Button size="sm" variant="ghost">
                <ArrowRight size={11} />
              </Button>
            </Link>
          }
        >
          {env.data ? (
            <>
              <BarChart
                data={(env.data.by_weather as Record<string, number | string>[]).map((r) => ({
                  key: String(r.weather),
                  label: WEATHER_LABEL[String(r.weather)] ?? String(r.weather),
                  value: Number(r.critical_per_run),
                  color: WEATHER_COLOR[String(r.weather)],
                  tip: [
                    { label: "Runs", value: int(Number(r.runs)) },
                    { label: "Grip", value: dec(Number(r.grip), 2) },
                    { label: "Conflicts / run", value: dec(Number(r.conflicts_per_run), 2) },
                    { label: "Critical / run", value: dec(Number(r.critical_per_run), 2) },
                    { label: "Contacts / run", value: dec(Number(r.collisions_per_run), 3) },
                    { label: "Excursions / run", value: dec(Number(r.off_track_per_run), 2) },
                    { label: "Mean min TTC", value: sec(Number(r.mean_min_ttc)) },
                  ],
                }))}
                height={160}
                yLabel="critical / run"
                valueFormat={(v) => dec(v, 1)}
              />
              <Caveat>{env.data.note}</Caveat>
            </>
          ) : (
            <Skeleton h={160} />
          )}
        </Panel>

        {/* ------------------------------------------- conflict types --- */}
        <Panel title="Conflict types" subtitle="Classified by SSAM-style heading angle, plus recorded racing intent.">
          {cb.data ? (
            <>
              <HBarChart
                data={conflictTypeTotals(cb.data.by_type_and_severity).map(
                  ([k, v]) => ({
                    key: k,
                    label: CONFLICT_TYPE_LABEL[k] ?? k,
                    value: v,
                    tip: [{ label: "Conflicts", value: int(v) }],
                  })
                )}
                labelWidth={106}
                valueFormat={(v) => int(v)}
              />
            </>
          ) : (
            <Skeleton h={160} />
          )}
        </Panel>

        {/* ------------------------------------------ driver interactions --- */}
        <Panel
          title="Driver interactions"
          subtitle="Highest critical-conflict rate per run in which both profiles were present."
          right={
            <Link href="/drivers">
              <Button size="sm" variant="ghost">
                <ArrowRight size={11} />
              </Button>
            </Link>
          }
        >
          {im.data ? (
            <>
              <HBarChart
                data={dedupePairs(im.data.cells)
                  .slice(0, 7)
                  .map((c) => ({
                    key: `${c.a}-${c.b}`,
                    label: `${ARCHETYPE_SHORT[c.a] ?? c.a} × ${ARCHETYPE_SHORT[c.b] ?? c.b}`,
                    value: c.critical_per_co_present_run ?? 0,
                    color: c.sparse ? "var(--seq-2)" : "var(--series-1)",
                    tip: [
                      { label: "Critical / co-present run", value: dec(c.critical_per_co_present_run, 3) },
                      { label: "Co-present runs", value: int(c.co_present_runs) },
                      { label: "Conflicts", value: int(c.conflicts) },
                      { label: "Median min TTC", value: sec(c.median_min_ttc) },
                      ...(c.sparse ? [{ label: "Note", value: "sparse (<15 runs)" }] : []),
                    ],
                  }))}
                labelWidth={148}
                valueFormat={(v) => dec(v, 3)}
              />
              <Legend
                className="mt-1"
                items={[
                  { label: "well-sampled", color: "var(--series-1)" },
                  { label: "sparse (<15 co-present runs)", color: "var(--seq-2)", muted: true },
                ]}
              />
            </>
          ) : (
            <Skeleton h={160} />
          )}
        </Panel>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <StressTestLauncher />
        {batchId && <AskPanel batchId={batchId} />}
      </div>

      <div className="mt-3">
        <Panel title="How this works" dense>
          <ol className="grid gap-2 text-[12px] leading-relaxed text-ink-3 md:grid-cols-4">
            {[
              [
                "1 · Generate",
                "A scenario generator samples driver composition, traffic, weather, grip, track width and human-error rates. Personalities stay fixed; conditions and draws vary.",
              ],
              [
                "2 · Simulate",
                "22 agents advance together at 20 Hz on a deterministic, vectorised engine. Agents act on a delayed view of their neighbours set by their own reaction time.",
              ],
              [
                "3 · Measure",
                "Trajectories are scored with established surrogate safety measures — TTC in closed form, PET by conflict-cell occupancy, SSAM-style conflict typing.",
              ],
              [
                "4 · Discover",
                "Qualifying conflicts are reduced to canonical patterns and counted by recurrence, then replayed and explained from the trajectory that produced them.",
              ],
            ].map(([h, b]) => (
              <li key={h} className="rounded border border-line bg-surface-2/40 px-2.5 py-2">
                <span className="mb-1 block text-[11px] font-semibold text-ink-2">{h}</span>
                {b}
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </>
  );
}

/** Roll the (type, severity) breakdown up to a total per conflict type. */
function conflictTypeTotals(
  rows: Record<string, number | string>[]
): [string, number][] {
  const totals = new Map<string, number>();
  for (const r of rows) {
    const k = String(r.conflict_type);
    totals.set(k, (totals.get(k) ?? 0) + Number(r.n));
  }
  return [...totals.entries()].sort((a, b) => b[1] - a[1]);
}

/** The matrix is symmetric; keep one cell per unordered pair. */
function dedupePairs<T extends { a: string; b: string; critical_per_co_present_run: number | null }>(
  cells: T[]
): T[] {
  const seen = new Set<string>();
  return cells
    .filter((c) => c.critical_per_co_present_run !== null)
    .sort(
      (x, y) =>
        (y.critical_per_co_present_run ?? 0) - (x.critical_per_co_present_run ?? 0)
    )
    .filter((c) => {
      const k = [c.a, c.b].sort().join("|");
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
}
