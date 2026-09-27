"use client";

import React from "react";

import { HBarChart, HeatmapGrid, LineChart } from "../../components/charts";
import { PageHeader, RequireBatch } from "../../components/Common";
import {
  Badge,
  Caveat,
  ErrorState,
  Panel,
  SegmentedControl,
  Select,
  Skeleton,
} from "../../components/ui";
import { api, SensitivityParam } from "../../lib/api";
import { dec, int, sec, signed } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";

export default function SensitivityPage() {
  return (
    <RequireBatch>
      <SensitivityScreen />
    </RequireBatch>
  );
}

function SensitivityScreen() {
  const { batchId } = useApp();
  const [outcome, setOutcome] = React.useState("n_critical");
  const [selected, setSelected] = React.useState<string | null>(null);

  const sens = useFetch(batchId ? () => api.sensitivity(batchId) : null, [batchId]);

  const params = sens.data?.parameters ?? [];
  const outcomes = sens.data?.outcomes ?? [];
  const active =
    params.find((p) => p.key === selected) ?? params[0] ?? null;

  const ranked = React.useMemo(
    () =>
      [...params].sort(
        (a, b) =>
          Math.abs(b.correlations[outcome] ?? 0) - Math.abs(a.correlations[outcome] ?? 0)
      ),
    [params, outcome]
  );

  const outcomeLabel = outcomes.find((o) => o.key === outcome)?.label ?? outcome;
  const fmtOutcome = (v: number) =>
    outcome === "min_ttc" ? dec(v, 3) : dec(v, 2);

  return (
    <>
      <PageHeader
        title="Sensitivity analysis"
        lede="Which parameters are actually associated with conflict frequency in this model — the difference between 'where is the dangerous corner' and 'what drives the dangerous interactions'."
        right={
          sens.data && (
            <span className="num text-[11px] text-ink-3">{int(sens.data.n_runs)} runs</span>
          )
        }
      />

      {sens.loading && !sens.data ? (
        <Skeleton h={420} />
      ) : sens.error ? (
        <ErrorState error={sens.error} onRetry={sens.reload} />
      ) : !sens.data || params.length === 0 ? (
        <Panel>
          <p className="py-8 text-center text-[12.5px] text-ink-3">
            {sens.data?.method_note ?? "Not enough runs for a sensitivity analysis."}
          </p>
        </Panel>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-end gap-3 rounded-md border border-line bg-surface-1/80 px-3 py-2.5">
            <Select
              label="Outcome"
              value={outcome}
              onChange={setOutcome}
              className="w-[220px]"
              options={outcomes.map((o) => ({ value: o.key, label: o.label }))}
            />
            <Caveat>{sens.data.method_note}</Caveat>
          </div>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
            <Panel
              title="Parameters ranked by association"
              subtitle={`Spearman rank correlation against ${outcomeLabel.toLowerCase()}. Click a bar to open its profile.`}
            >
              <HBarChart
                data={ranked.map((p) => {
                  const r = p.correlations[outcome] ?? 0;
                  return {
                    key: p.key,
                    label: p.label,
                    value: Math.abs(r),
                    color: r >= 0 ? "var(--series-1)" : "var(--series-3)",
                    glyph: r >= 0 ? "↑" : "↓",
                    tip: [
                      { label: "rho", value: signed(r, 3) },
                      {
                        label: "Direction",
                        value:
                          r >= 0
                            ? `higher ${p.label.toLowerCase()} → more ${outcomeLabel.toLowerCase()}`
                            : `higher ${p.label.toLowerCase()} → less ${outcomeLabel.toLowerCase()}`,
                      },
                      { label: "Runs", value: int(p.n) },
                      { label: "Sampled range", value: `${dec(p.range[0], 3)} – ${dec(p.range[1], 3)}` },
                    ],
                  };
                })}
                labelWidth={208}
                valueFormat={(v) => dec(v, 3)}
                maxOverride={1}
                onSelect={(d) => setSelected(d.key)}
                selectedKey={active?.key}
              />
              <div className="mt-2 flex flex-wrap items-center gap-3 border-t border-line pt-2">
                <span className="flex items-center gap-1.5 text-[10.5px] text-ink-3">
                  <span className="num" style={{ color: "var(--series-1)" }} aria-hidden>
                    ↑
                  </span>
                  positive — more of this, more {outcomeLabel.toLowerCase()}
                </span>
                <span className="flex items-center gap-1.5 text-[10.5px] text-ink-3">
                  <span className="num" style={{ color: "var(--series-3)" }} aria-hidden>
                    ↓
                  </span>
                  negative — more of this, less {outcomeLabel.toLowerCase()}
                </span>
              </div>
              <Caveat>
                Bars show |rho|; the arrow and colour carry the sign, so direction is
                never conveyed by colour alone.
              </Caveat>
            </Panel>

            {active && (
              <Panel
                title={active.label}
                subtitle={`${outcomeLabel} across equal-count bands of this parameter.`}
                right={
                  <Badge>
                    rho {signed(active.correlations[outcome] ?? 0, 3)}
                  </Badge>
                }
              >
                <LineChart
                  series={[
                    {
                      key: "outcome",
                      label: outcomeLabel,
                      color: "var(--series-1)",
                      points: active.bands.map((b) => ({
                        x: b.mid,
                        y: b[outcome] === null || b[outcome] === undefined ? null : Number(b[outcome]),
                      })),
                    },
                  ]}
                  height={200}
                  xLabel={active.label}
                  yLabel={outcomeLabel}
                  xFormat={(v) => dec(v, 2)}
                  yFormat={fmtOutcome}
                  markers
                  area
                />
                <div className="mt-2 overflow-x-auto border-t border-line pt-2.5">
                  <table className="w-full text-[11.5px]">
                    <thead>
                      <tr>
                        {["Band", "Runs", "Conflicts", "Critical", "Contacts", "Excursions", "Min TTC", "Runs w/ critical"].map(
                          (h) => (
                            <th
                              key={h}
                              className="label-xs !text-[9px] border-b border-line-strong px-1.5 py-1 text-right first:text-left"
                            >
                              {h}
                            </th>
                          )
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {active.bands.map((b, i) => (
                        <tr key={i} className="border-b border-line/60">
                          <td className="num px-1.5 py-1 text-ink-2">
                            {dec(b.lo, 2)}–{dec(b.hi, 2)}
                          </td>
                          <td className="num px-1.5 py-1 text-right text-ink-3">{int(b.runs)}</td>
                          <td className="num px-1.5 py-1 text-right text-ink">
                            {dec(Number(b.n_conflicts), 2)}
                          </td>
                          <td className="num px-1.5 py-1 text-right text-ink">
                            {dec(Number(b.n_critical), 2)}
                          </td>
                          <td className="num px-1.5 py-1 text-right text-ink">
                            {dec(Number(b.n_collisions), 3)}
                          </td>
                          <td className="num px-1.5 py-1 text-right text-ink">
                            {dec(Number(b.n_off_track), 2)}
                          </td>
                          <td className="num px-1.5 py-1 text-right text-ink">
                            {b.min_ttc === null ? "—" : dec(Number(b.min_ttc), 3)}
                          </td>
                          <td className="num px-1.5 py-1 text-right text-ink-2">
                            {dec(Number(b.fraction_runs_with_critical) * 100, 1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            )}
          </div>

          {/* ------------------------------------------ two-way interactions --- */}
          {sens.data.interactions.length > 0 && (
            <div className="mt-3">
              <Panel
                title="Parameter combinations"
                subtitle="Critical conflicts per run across a grid of two parameters at once — the question the project is actually about."
              >
                <div className="grid gap-5 lg:grid-cols-2">
                  {sens.data.interactions.map((inter) => {
                    const rows = inter.a_edges.slice(0, -1).map((lo, i) => ({
                      key: `a${i}`,
                      label: `${dec(lo, 2)}–${dec(inter.a_edges[i + 1], 2)}`,
                    }));
                    const cols = inter.b_edges.slice(0, -1).map((lo, j) => ({
                      key: `b${j}`,
                      label: `${dec(lo, 2)}–${dec(inter.b_edges[j + 1], 2)}`,
                    }));
                    return (
                      <div key={inter.label}>
                        <p className="label-xs mb-2">{inter.label}</p>
                        <HeatmapGrid
                          rows={rows}
                          cols={cols}
                          cells={inter.cells.map((c) => ({
                            i: c.i,
                            j: c.j,
                            value: c.critical_per_run,
                            label: `${paramShort(inter.a_key)} ${dec(c.a_lo, 2)}–${dec(
                              c.a_hi,
                              2
                            )} × ${paramShort(inter.b_key)} ${dec(c.b_lo, 2)}–${dec(c.b_hi, 2)}`,
                            muted: c.runs < 25,
                            tip: [
                              { label: "Runs in cell", value: int(c.runs) },
                              { label: "Critical / run", value: dec(c.critical_per_run, 3) },
                              { label: "Conflicts / run", value: dec(c.conflicts_per_run, 3) },
                              { label: "Contacts / run", value: dec(c.collisions_per_run, 3) },
                              ...(c.runs < 25 ? [{ label: "Note", value: "few runs in this cell" }] : []),
                            ],
                          }))}
                          cellSize={54}
                          rowLabelWidth={84}
                          legendLabel="critical / run"
                          valueFormat={(v) => dec(v, 2)}
                        />
                        <p className="mt-1 text-[10px] text-ink-3">
                          Rows: {paramShort(inter.a_key)} · Columns: {paramShort(inter.b_key)}
                        </p>
                      </div>
                    );
                  })}
                </div>
                <Caveat>
                  Cells marked with a dot rest on fewer than 25 runs. Bands are tertiles
                  of each sampled parameter.
                </Caveat>
              </Panel>
            </div>
          )}
        </>
      )}
    </>
  );
}

function paramShort(key: string): string {
  const m: Record<string, string> = {
    traffic_density_measured: "traffic density",
    grip: "grip",
    trait_aggression: "field aggression",
    trait_late_braking_tendency: "late braking",
    track_width_multiplier: "track width",
    error_rate_multiplier: "error rate",
    visibility: "visibility",
  };
  return m[key] ?? key.replace(/_/g, " ");
}
