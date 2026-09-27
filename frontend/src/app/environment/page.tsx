"use client";

import React from "react";

import { BarChart, HBarChart, StackedBarChart } from "../../components/charts";
import { Metric, PageHeader, RequireBatch } from "../../components/Common";
import {
  Caveat,
  ErrorState,
  KeyValue,
  Panel,
  SegmentedControl,
  Skeleton,
} from "../../components/ui";
import { api } from "../../lib/api";
import { dec, int, sec } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import {
  CONFLICT_TYPE_COLOR,
  CONFLICT_TYPE_LABEL,
  CONFLICT_TYPE_ORDER,
  WEATHER_COLOR,
  WEATHER_LABEL,
  WEATHER_ORDER,
} from "../../lib/theme";

const OUTCOMES = [
  { value: "conflicts_per_run", label: "Conflicts", unit: "per run", digits: 2 },
  { value: "critical_per_run", label: "Critical", unit: "per run", digits: 2 },
  { value: "near_misses_per_run", label: "Near misses", unit: "per run", digits: 2 },
  { value: "collisions_per_run", label: "Contacts", unit: "per run", digits: 3 },
  { value: "off_track_per_run", label: "Excursions", unit: "per run", digits: 2 },
  { value: "spins_per_run", label: "Spins", unit: "per run", digits: 3 },
  { value: "mean_min_ttc", label: "Mean min TTC", unit: "s", digits: 3 },
  { value: "overtakes_completed_per_run", label: "Overtakes", unit: "per run", digits: 2 },
] as const;

type OutcomeKey = (typeof OUTCOMES)[number]["value"];

export default function EnvironmentPage() {
  return (
    <RequireBatch>
      <EnvironmentAnalysis />
    </RequireBatch>
  );
}

function EnvironmentAnalysis() {
  const { batchId } = useApp();
  const [outcome, setOutcome] = React.useState<OutcomeKey>("critical_per_run");

  const env = useFetch(batchId ? () => api.environment(batchId) : null, [batchId]);
  const sens = useFetch(batchId ? () => api.sensitivity(batchId) : null, [batchId]);

  const rows = React.useMemo(() => {
    const r = (env.data?.by_weather ?? []) as Record<string, number | string>[];
    return [...r].sort(
      (a, b) =>
        WEATHER_ORDER.indexOf(String(a.weather) as (typeof WEATHER_ORDER)[number]) -
        WEATHER_ORDER.indexOf(String(b.weather) as (typeof WEATHER_ORDER)[number])
    );
  }, [env.data]);

  const meta = OUTCOMES.find((o) => o.value === outcome)!;

  const gripParam = sens.data?.parameters.find((p) => p.key === "grip");
  const visParam = sens.data?.parameters.find((p) => p.key === "visibility");
  const tyreParam = sens.data?.parameters.find((p) => p.key === "tyre_condition");

  return (
    <>
      <PageHeader
        title="Environment analysis"
        lede="How conditions changed the interactions this model produced. Weather presets resolve into grip, visibility and spray — the three scalars the engine actually consumes."
      />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Panel
          title="Outcome by condition"
          subtitle={`${meta.label}, ${meta.unit}`}
          right={
            <SegmentedControl
              value={outcome}
              onChange={setOutcome}
              options={OUTCOMES.map((o) => ({ value: o.value, label: o.label }))}
              size="sm"
            />
          }
          note={env.data?.note}
        >
          {env.loading && !env.data ? (
            <Skeleton h={230} />
          ) : env.error ? (
            <ErrorState error={env.error} onRetry={env.reload} />
          ) : (
            <BarChart
              data={rows.map((r) => ({
                key: String(r.weather),
                label: WEATHER_LABEL[String(r.weather)] ?? String(r.weather),
                value: Number(r[outcome] ?? 0),
                color: WEATHER_COLOR[String(r.weather)],
                tip: [
                  { label: "Runs", value: int(Number(r.runs)) },
                  { label: "Grip", value: dec(Number(r.grip), 3) },
                  { label: "Visibility", value: dec(Number(r.visibility), 3) },
                  { label: "Spray", value: dec(Number(r.spray), 2) },
                  { label: "Conflicts / run", value: dec(Number(r.conflicts_per_run), 2) },
                  { label: "Critical / run", value: dec(Number(r.critical_per_run), 2) },
                  { label: "Contacts / run", value: dec(Number(r.collisions_per_run), 3) },
                  { label: "Excursions / run", value: dec(Number(r.off_track_per_run), 2) },
                  { label: "Mean min TTC", value: sec(Number(r.mean_min_ttc)) },
                  { label: "Peak decel", value: `${dec(Number(r.mean_max_decel) / 9.81, 2)} g` },
                ],
              }))}
              height={230}
              yLabel={`${meta.label} ${meta.unit}`}
              valueFormat={(v) => dec(v, meta.digits === 3 ? 2 : meta.digits)}
            />
          )}
        </Panel>

        <Panel
          title="What the model actually says about rain"
          subtitle="Read the two directions together — they point opposite ways."
        >
          {rows.length >= 2 ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr>
                      <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-left">
                        Condition
                      </th>
                      {["Runs", "Grip", "Vis.", "Conf/run", "Crit/run", "Contact/run", "Excur/run", "Mean TTC"].map(
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
                    {rows.map((r) => (
                      <tr key={String(r.weather)} className="border-b border-line/60">
                        <td className="px-2 py-1.5">
                          <span className="flex items-center gap-1.5">
                            <span
                              className="inline-block h-[8px] w-[8px] rounded-[1px]"
                              style={{ background: WEATHER_COLOR[String(r.weather)] }}
                              aria-hidden
                            />
                            <span className="text-ink-2">
                              {WEATHER_LABEL[String(r.weather)] ?? String(r.weather)}
                            </span>
                          </span>
                        </td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{int(Number(r.runs))}</td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{dec(Number(r.grip), 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink-2">{dec(Number(r.visibility), 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(Number(r.conflicts_per_run), 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(Number(r.critical_per_run), 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(Number(r.collisions_per_run), 3)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(Number(r.off_track_per_run), 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(Number(r.mean_min_ttc), 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <WetFinding rows={rows} />
            </>
          ) : (
            <Skeleton h={230} />
          )}
        </Panel>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Panel
          title="Conflict type mix by condition"
          subtitle="Share of conflicts by type within each condition."
        >
          {env.data ? (
            <StackedBarChart
              categories={rows.map((r) => ({
                key: String(r.weather),
                label: WEATHER_LABEL[String(r.weather)] ?? String(r.weather),
              }))}
              series={CONFLICT_TYPE_ORDER.filter((t) =>
                env.data!.conflict_types_by_weather.some((c) => c.conflict_type === t)
              ).map((t) => ({
                key: t,
                label: CONFLICT_TYPE_LABEL[t] ?? t,
                color: CONFLICT_TYPE_COLOR[t],
                values: rows.map(
                  (r) =>
                    env.data!.conflict_types_by_weather.find(
                      (c) => c.weather === String(r.weather) && c.conflict_type === t
                    )?.n ?? 0
                ),
              }))}
              normalise
              height={220}
              valueFormat={(v) => int(v)}
            />
          ) : (
            <Skeleton h={230} />
          )}
        </Panel>

        <Panel
          title="Most flagged locations, by condition"
          subtitle="The hotspot ranking is not the same in every condition."
        >
          {env.data ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {WEATHER_ORDER.filter(
                (w) => (env.data!.top_locations_by_weather[w] ?? []).length > 0
              ).map((w) => (
                <div key={w}>
                  <p className="label-xs mb-1.5" style={{ color: WEATHER_COLOR[w] }}>
                    {WEATHER_LABEL[w]}
                  </p>
                  <ol className="space-y-1">
                    {(env.data!.top_locations_by_weather[w] ?? []).map((l, i) => (
                      <li key={i} className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-[11px] text-ink-2">
                          {l.turn_number !== null && (
                            <span className="num mr-1 text-ink-3">T{l.turn_number}</span>
                          )}
                          {l.location}
                        </span>
                        <span className="num shrink-0 text-[11px] text-ink">{int(l.n)}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          ) : (
            <Skeleton h={230} />
          )}
        </Panel>
      </div>

      {/* ------------------------------------------ continuous variables --- */}
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        {[
          { param: gripParam, title: "Grip", note: "Multiplier on both friction ceilings." },
          {
            param: visParam,
            title: "Visibility",
            note: "Scales usable perception range, which lengthens effective reaction distance.",
          },
          {
            param: tyreParam,
            title: "Tyre condition",
            note: "1.0 fresh to 0.0 fully worn, as modelled. Removes grip on top of the weather term.",
          },
        ].map(({ param, title, note }) => (
          <Panel key={title} title={title} subtitle={note}>
            {param ? (
              <>
                <HBarChart
                  data={param.bands.map((b) => ({
                    key: `${b.lo}`,
                    label: `${dec(b.lo, 2)}–${dec(b.hi, 2)}`,
                    value: Number(b.n_critical ?? 0),
                    tip: [
                      { label: "Runs", value: int(b.runs) },
                      { label: "Critical / run", value: dec(Number(b.n_critical), 3) },
                      { label: "Conflicts / run", value: dec(Number(b.n_conflicts), 3) },
                      { label: "Contacts / run", value: dec(Number(b.n_collisions), 3) },
                      { label: "Excursions / run", value: dec(Number(b.n_off_track), 3) },
                      { label: "Mean min TTC", value: sec(Number(b.min_ttc)) },
                    ],
                  }))}
                  labelWidth={86}
                  valueFormat={(v) => dec(v, 2)}
                />
                <div className="mt-2 border-t border-line pt-2">
                  <KeyValue
                    cols={2}
                    rows={[
                      {
                        label: "rho vs critical",
                        value: dec(param.correlations.n_critical, 3),
                      },
                      {
                        label: "rho vs excursions",
                        value: dec(param.correlations.n_off_track, 3),
                      },
                    ]}
                  />
                </div>
              </>
            ) : (
              <Skeleton h={180} />
            )}
          </Panel>
        ))}
      </div>

      {env.data && (
        <div className="mt-3">
          <Panel
            title="Weather presets"
            subtitle="These are modelling assumptions, not measured track data."
            dense
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr>
                    <th className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-left">
                      Preset
                    </th>
                    {["Grip", "Visibility", "Spray", "Track temp", "Ambient", "Wind"].map((h) => (
                      <th
                        key={h}
                        className="label-xs !text-[9.5px] border-b border-line-strong px-2 py-1.5 text-right"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {WEATHER_ORDER.map((w) => {
                    const p = env.data!.presets[w];
                    if (!p) return null;
                    return (
                      <tr key={w} className="border-b border-line/60">
                        <td className="px-2 py-1.5 text-ink-2">{WEATHER_LABEL[w]}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(p.grip, 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(p.visibility, 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(p.spray, 2)}</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(p.track_temp, 0)}°C</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(p.ambient_temp, 0)}°C</td>
                        <td className="num px-2 py-1.5 text-right text-ink">{dec(p.wind, 0)} m/s</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Caveat>
              Each run also draws within-condition jitter, so two &quot;wet&quot; runs are
              not identical. The grip and visibility columns in the tables above are the
              realised means, not these nominal values.
            </Caveat>
          </Panel>
        </div>
      )}
    </>
  );
}

/**
 * States the model's actual finding about rain, computed from the data rather than
 * asserted — including when it contradicts the expected direction.
 */
function WetFinding({ rows }: { rows: Record<string, number | string>[] }) {
  const dry = rows.find((r) => r.weather === "DRY");
  const wet = rows.find((r) => r.weather === "HEAVY_RAIN") ?? rows.find((r) => r.weather === "WET");
  if (!dry || !wet) return null;

  const dConf = Number(dry.conflicts_per_run);
  const wConf = Number(wet.conflicts_per_run);
  const dTtc = Number(dry.mean_min_ttc);
  const wTtc = Number(wet.mean_min_ttc);
  const dOff = Number(dry.off_track_per_run);
  const wOff = Number(wet.off_track_per_run);

  const fewer = wConf < dConf;
  const closer = wTtc < dTtc;
  const moreExcursions = wOff > dOff;

  return (
    <div className="mt-3 border-t border-line pt-2.5">
      <p className="text-[12px] leading-relaxed text-ink-2">
        In this batch, going from dry to{" "}
        {(WEATHER_LABEL[String(wet.weather)] ?? String(wet.weather)).toLowerCase()}{" "}
        changed conflicts per run from <span className="num">{dec(dConf, 2)}</span> to{" "}
        <span className="num">{dec(wConf, 2)}</span>, mean minimum TTC from{" "}
        <span className="num">{dec(dTtc, 2)} s</span> to{" "}
        <span className="num">{dec(wTtc, 2)} s</span>, and off-track excursions per run
        from <span className="num">{dec(dOff, 2)}</span> to{" "}
        <span className="num">{dec(wOff, 2)}</span>.
      </p>
      {fewer && closer && moreExcursions && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-3">
          So this model produces <span className="text-ink-2">fewer but closer</span>{" "}
          conflicts in the wet, alongside markedly more excursions. The mechanism is
          visible in the engine: lower grip lowers cornering speeds, which shrinks the
          speed differentials that trigger overtake attempts, so fewer interactions
          develop — but the ones that do have less braking margin, and more cars simply
          run out of road. That is a property of this model, not a finding about racing,
          and it runs counter to the intuition that rain must raise conflict counts. It
          is reported as measured rather than adjusted to match expectation.
        </p>
      )}
    </div>
  );
}
