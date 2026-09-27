"use client";

import React from "react";

import { HBarChart, HeatmapGrid, Legend } from "../../components/charts";
import { Metric, PageHeader, RequireBatch } from "../../components/Common";
import {
  Badge,
  Caveat,
  DataTable,
  ErrorState,
  Panel,
  SegmentedControl,
  Skeleton,
} from "../../components/ui";
import { api, Archetype, MatrixCell } from "../../lib/api";
import { dec, int, pct, sec } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_COLOR,
  CONFLICT_TYPE_LABEL,
  WEATHER_COLOR,
  WEATHER_LABEL,
} from "../../lib/theme";

type Cell = "critical_per_co_present_run" | "conflicts_per_co_present_run" | "median_min_ttc";

const CELL_OPTIONS: { value: Cell; label: string; title: string }[] = [
  {
    value: "critical_per_co_present_run",
    label: "Critical / run",
    title: "Critical conflicts per run in which both profiles were present",
  },
  {
    value: "conflicts_per_co_present_run",
    label: "Conflicts / run",
    title: "All flagged conflicts per run in which both profiles were present",
  },
  {
    value: "median_min_ttc",
    label: "1 / median TTC",
    title: "Inverse median minimum TTC — higher means their conflicts came closer",
  },
];

export default function DriversPage() {
  return (
    <RequireBatch>
      <DriverAnalysis />
    </RequireBatch>
  );
}

function DriverAnalysis() {
  const { batchId, meta } = useApp();
  const [cellMetric, setCellMetric] = React.useState<Cell>("critical_per_co_present_run");
  const [sel, setSel] = React.useState<{ i: number; j: number } | null>(null);

  const im = useFetch(batchId ? () => api.interactions(batchId) : null, [batchId]);
  const archetypes = meta?.archetypes ?? [];

  const cellValue = (c: MatrixCell): number | null => {
    if (cellMetric === "median_min_ttc")
      return c.median_min_ttc && c.median_min_ttc > 0 ? 1 / c.median_min_ttc : null;
    return c[cellMetric];
  };

  const rows = (im.data?.archetypes ?? []).map((a) => ({
    key: a.id,
    label: a.label,
  }));
  // Rotated column headers have far less room than row labels, so they use the
  // short form rather than being truncated mid-word.
  const cols = (im.data?.archetypes ?? []).map((a) => ({
    key: a.id,
    label: ARCHETYPE_SHORT[a.id] ?? a.label,
  }));

  const cells = React.useMemo(() => {
    if (!im.data) return [];
    return im.data.cells.map((c) => ({
      i: c.i,
      j: c.j,
      value: c.co_present_runs === 0 ? null : cellValue(c),
      label: `${ARCHETYPE_SHORT[c.a] ?? c.a} × ${ARCHETYPE_SHORT[c.b] ?? c.b}`,
      muted: c.sparse,
      tip: [
        { label: "Co-present runs", value: int(c.co_present_runs) },
        { label: "Conflicts", value: int(c.conflicts) },
        { label: "Critical", value: int(c.critical) },
        { label: "Contacts", value: int(c.collisions) },
        {
          label: "Critical per co-present run",
          value: dec(c.critical_per_co_present_run, 3),
        },
        { label: "Median min TTC", value: sec(c.median_min_ttc) },
        {
          label: "Dominant type",
          value: c.dominant_conflict_type
            ? CONFLICT_TYPE_LABEL[c.dominant_conflict_type] ?? c.dominant_conflict_type
            : "—",
        },
        ...(c.sparse
          ? [{ label: "Note", value: "sparse — fewer than 15 co-present runs" }]
          : []),
      ],
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [im.data, cellMetric]);

  const selectedCell =
    sel && im.data
      ? im.data.cells.find((c) => c.i === sel.i && c.j === sel.j) ?? null
      : null;

  return (
    <>
      <PageHeader
        title="Driver analysis"
        lede="How behavioural profiles interacted. Rates are normalised by co-presence, so a profile that happened to be sampled more often does not look more conflict-prone for that reason alone."
      />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Panel
          title="Behavioural interaction matrix"
          subtitle={CELL_OPTIONS.find((o) => o.value === cellMetric)?.title}
          right={
            <SegmentedControl
              value={cellMetric}
              onChange={(v) => {
                setCellMetric(v);
                setSel(null);
              }}
              options={CELL_OPTIONS}
              size="sm"
            />
          }
          note={im.data?.note}
        >
          {im.loading && !im.data ? (
            <Skeleton h={420} />
          ) : im.error ? (
            <ErrorState error={im.error} onRetry={im.reload} />
          ) : im.data ? (
            <HeatmapGrid
              rows={rows}
              cols={cols}
              cells={cells}
              selected={sel}
              onSelect={(c) => setSel({ i: c.i, j: c.j })}
              legendLabel={CELL_OPTIONS.find((o) => o.value === cellMetric)?.label}
              valueFormat={(v) => dec(v, cellMetric === "median_min_ttc" ? 2 : 3)}
              cellSize={40}
              rowLabelWidth={130}
              note="Click a cell for the breakdown."
            />
          ) : null}
        </Panel>

        <div className="flex min-w-0 flex-col gap-3">
          {selectedCell ? (
            <Panel
              title="Pairing detail"
              subtitle={`${ARCHETYPE_SHORT[selectedCell.a] ?? selectedCell.a} against ${
                ARCHETYPE_SHORT[selectedCell.b] ?? selectedCell.b
              }`}
              right={
                selectedCell.sparse ? (
                  <Badge color="var(--warning)" glyph="△">
                    sparse
                  </Badge>
                ) : null
              }
            >
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                <Metric label="Co-present runs" value={int(selectedCell.co_present_runs)} />
                <Metric label="Conflicts" value={int(selectedCell.conflicts)} />
                <Metric label="Critical" value={int(selectedCell.critical)} />
                <Metric label="Contacts" value={int(selectedCell.collisions)} />
                <Metric
                  label="Critical / run"
                  value={dec(selectedCell.critical_per_co_present_run, 3)}
                />
                <Metric label="Median min TTC" value={sec(selectedCell.median_min_ttc)} />
              </div>

              <p className="mt-3 border-t border-line pt-2.5 text-[12px] leading-relaxed text-ink-2">
                These two behavioural profiles produced{" "}
                <span className="num">{int(selectedCell.critical)}</span> critical
                conflicts across{" "}
                <span className="num">{int(selectedCell.co_present_runs)}</span> runs in
                which both were on track
                {selectedCell.dominant_conflict_type && (
                  <>
                    , most often typed{" "}
                    {(
                      CONFLICT_TYPE_LABEL[selectedCell.dominant_conflict_type] ??
                      selectedCell.dominant_conflict_type
                    ).toLowerCase()}
                  </>
                )}
                {Object.keys(selectedCell.weather_mix).length > 0 && (
                  <>
                    , and predominantly in{" "}
                    {Object.entries(selectedCell.weather_mix)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 2)
                      .map(([k]) => (WEATHER_LABEL[k] ?? k).toLowerCase())
                      .join(" and ")}{" "}
                    conditions
                  </>
                )}
                .{" "}
                {selectedCell.sparse &&
                  "This cell rests on fewer than 15 co-present runs, so treat it as indicative only. "}
                Neither profile is unsafe: these are simulation parameterisations, and a
                higher rate means these two parameter sets produced more critical
                interactions under this model's assumptions.
              </p>

              {Object.keys(selectedCell.conflict_type_mix).length > 0 && (
                <div className="mt-3 border-t border-line pt-2.5">
                  <p className="label-xs mb-1.5">Conflict type mix</p>
                  <ul className="space-y-1">
                    {Object.entries(selectedCell.conflict_type_mix)
                      .sort((a, b) => b[1] - a[1])
                      .map(([k, v]) => (
                        <li key={k} className="flex items-center justify-between gap-2">
                          <span className="flex items-center gap-1.5">
                            <span
                              className="inline-block h-[8px] w-[8px] rounded-[1px]"
                              style={{
                                background: CONFLICT_TYPE_COLOR[k] ?? "var(--series-1)",
                              }}
                              aria-hidden
                            />
                            <span className="text-[11.5px] text-ink-2">
                              {CONFLICT_TYPE_LABEL[k] ?? k}
                            </span>
                          </span>
                          <span className="num text-[11.5px] text-ink">{int(v)}</span>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </Panel>
          ) : (
            <Panel title="Pairing detail">
              <p className="py-8 text-center text-[12px] text-ink-3">
                Select a cell in the matrix to see its breakdown.
              </p>
            </Panel>
          )}

          <Panel
            title="Highest-rate pairings"
            subtitle="Deduplicated; sparse cells marked."
          >
            {im.data ? (
              <HBarChart
                data={dedupe(im.data.cells)
                  .slice(0, 12)
                  .map((c) => ({
                    key: `${c.a}-${c.b}`,
                    label: `${ARCHETYPE_SHORT[c.a] ?? c.a} × ${ARCHETYPE_SHORT[c.b] ?? c.b}`,
                    value: c.critical_per_co_present_run ?? 0,
                    color: c.sparse ? "var(--seq-2)" : "var(--series-1)",
                    tip: [
                      { label: "Critical / co-present run", value: dec(c.critical_per_co_present_run, 3) },
                      { label: "Co-present runs", value: int(c.co_present_runs) },
                      { label: "Median min TTC", value: sec(c.median_min_ttc) },
                    ],
                  }))}
                labelWidth={172}
                valueFormat={(v) => dec(v, 3)}
                onSelect={(d) => {
                  const cell = im.data!.cells.find((c) => `${c.a}-${c.b}` === d.key);
                  if (cell) setSel({ i: cell.i, j: cell.j });
                }}
              />
            ) : (
              <Skeleton h={260} />
            )}
            <Legend
              className="mt-1"
              items={[
                { label: "well-sampled", color: "var(--series-1)" },
                { label: "sparse (<15 co-present runs)", color: "var(--seq-2)", muted: true },
              ]}
            />
          </Panel>
        </div>
      </div>

      {/* ---------------------------------------------- archetype catalogue --- */}
      <div className="mt-3">
        <Panel
          title="Behavioural archetypes"
          subtitle="The persistent profiles the agents are built from."
          note="Every value is a simulation parameter, not a measured property of any real driver. Where a profile is labelled after a real driver it would be a behavioural abstraction over publicly observable racing behaviour — never a digital twin."
        >
          <DataTable<Archetype>
            rows={archetypes}
            rowKey={(r) => r.id}
            columns={[
              {
                key: "label",
                header: "Archetype",
                width: "170px",
                render: (r) => (
                  <span>
                    <span className="block text-[12px] text-ink">{r.label}</span>
                    <span className="block text-[10px] leading-snug text-ink-3">{r.note}</span>
                  </span>
                ),
              },
              { key: "ag", header: "Aggr.", align: "right", render: (r) => dec(r.aggression, 2), sortValue: (r) => r.aggression },
              { key: "rt", header: "Risk", align: "right", render: (r) => dec(r.risk_tolerance, 2), sortValue: (r) => r.risk_tolerance },
              { key: "ow", header: "Overtake", align: "right", render: (r) => dec(r.overtake_willingness, 2), sortValue: (r) => r.overtake_willingness },
              { key: "dt", header: "Defend", align: "right", render: (r) => dec(r.defensive_tendency, 2), sortValue: (r) => r.defensive_tendency },
              { key: "react", header: "React (s)", align: "right", render: (r) => dec(r.reaction_time, 2), sortValue: (r) => r.reaction_time },
              { key: "lb", header: "Late brake", align: "right", render: (r) => dec(r.late_braking_tendency, 2), sortValue: (r) => r.late_braking_tendency },
              { key: "bc", header: "Consistency", align: "right", render: (r) => dec(r.braking_consistency, 2), sortValue: (r) => r.braking_consistency },
              { key: "pr", header: "Predictability", align: "right", render: (r) => dec(r.predictability, 2), sortValue: (r) => r.predictability },
              { key: "ep", header: "Error ×", align: "right", render: (r) => dec(r.error_probability, 2), sortValue: (r) => r.error_probability },
              { key: "pm", header: "Pace ×", align: "right", render: (r) => dec(r.pace_multiplier, 3), sortValue: (r) => r.pace_multiplier },
              {
                key: "present",
                header: "In runs",
                align: "right",
                render: (r) => {
                  const a = im.data?.archetypes.find((x) => x.id === r.id);
                  return a ? int(a.present_in_runs) : "—";
                },
              },
            ]}
          />
          <Caveat>
            Across a batch a profile does not change. What varies run to run is a
            perturbation around it, scaled by that agent&apos;s own consistency and
            predictability — so a High Consistency agent barely moves from its profile
            while an Unpredictable one varies several times as much.
          </Caveat>
        </Panel>
      </div>
    </>
  );
}

function dedupe(cells: MatrixCell[]): MatrixCell[] {
  const seen = new Set<string>();
  return cells
    .filter((c) => c.critical_per_co_present_run !== null && c.co_present_runs > 0)
    .sort(
      (a, b) =>
        (b.critical_per_co_present_run ?? 0) - (a.critical_per_co_present_run ?? 0)
    )
    .filter((c) => {
      const k = [c.a, c.b].sort().join("|");
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
}
