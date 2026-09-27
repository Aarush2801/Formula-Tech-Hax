"use client";

import { Play, Zap } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "../../../components/Common";
import { driverSummary, PartStatusBadge, RequireCar, usePassportCatalogue } from "../../../components/passport";
import {
  Button,
  Caveat,
  Column,
  DataTable,
  EmptyState,
  ErrorState,
  Panel,
  Skeleton,
  StatTile,
} from "../../../components/ui";
import { datetime, dec, int, sec } from "../../../lib/format";
import {
  Car,
  CloseCall,
  partLabel,
  passportApi,
  StressPartReport,
} from "../../../lib/passport";
import { useFetch } from "../../../lib/store";
import { WEATHER_LABEL } from "../../../lib/theme";

const AMBER = 70;
const RED = 90;

export default function ReadinessPage() {
  return (
    <>
      <PageHeader
        title="Readiness report"
        lede="What the latest stress test predicts for the next race: how much life each part is likely to use, what to replace or inspect first, and the closest calls to watch back."
      />
      <RequireCar>{(car) => <Report key={car.id} car={car} />}</RequireCar>
    </>
  );
}

function Report({ car }: { car: Car }) {
  const { archetypes } = usePassportCatalogue();
  const latest = useFetch(() => passportApi.latestStressTest(car.id), [car.id]);

  if (latest.error) return <ErrorState error={latest.error} onRetry={latest.reload} />;
  if (!latest.data) return <Skeleton h={320} />;
  const r = latest.data.result;
  if (!r) {
    return (
      <EmptyState
        title="No stress test for this car yet"
        body="The readiness report is built from a stress test. Run one and come back."
        action={
          <Link href="/passport/stress-test">
            <Button variant="primary">
              <Zap size={12} /> Run a stress test
            </Button>
          </Link>
        }
      />
    );
  }

  const red = r.parts.filter((p) => p.status === "red").length;
  const amber = r.parts.filter((p) => p.status === "amber").length;

  const closeCols: Column<CloseCall>[] = [
    { key: "ttc", header: "Min TTC", align: "right", render: (c) => sec(c.min_ttc), sortValue: (c) => c.min_ttc },
    { key: "pet", header: "Min PET", align: "right", render: (c) => sec(c.min_pet) },
    { key: "contacts", header: "Contacts", align: "right", render: (c) => int(c.n_collisions + c.n_light_contacts) },
    {
      key: "replay",
      header: "",
      align: "right",
      render: (c) =>
        c.has_replay ? (
          <Link href={`/replay?run=${c.run_id}`} className="inline-flex items-center gap-1 text-[11px] text-[color:var(--accent)] hover:underline">
            <Play size={10} /> Replay
          </Link>
        ) : (
          <span className="text-[11px] text-ink-3">no replay</span>
        ),
    },
  ];

  return (
    <div className="grid gap-3">
      <p className="text-[11.5px] text-ink-3">
        {int(r.n_races)} simulated races · {r.track_id.replace(/_/g, " ")} ·{" "}
        {WEATHER_LABEL[r.weather] ?? r.weather}
        {r.driver ? ` · driver: ${driverSummary(r.driver, archetypes)}` : ""}
        {r.created_at ? ` · ${datetime(r.created_at)}` : ""}
      </p>

      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Replace before race" value={int(red)} tone={red ? "critical" : "good"} glyph={red ? "✕" : "●"} sub="median prediction at or above 90%" />
        <StatTile label="Inspect" value={int(amber)} tone={amber ? "warning" : "good"} glyph={amber ? "▲" : "●"} sub="median prediction 70–90%" />
        <StatTile label="Close calls" value={int(r.n_close_calls)} sub={`of ${int(r.n_races)} races had a pair of cars below 0.8 s TTC`} />
        <StatTile label="Cost forecast" value={dec(r.cost_forecast.total, 0)} sub="illustrative, per race" />
      </div>

      <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
        <Panel
          title="Predicted life used after the next race"
          subtitle="Bar spans the lowest to highest outcome across the simulated races; the dot is the median, the hollow tick is today's condition. Ticks mark 70% and 90%."
        >
          <WearChart parts={r.parts} />
        </Panel>

        <div className="grid content-start gap-3">
          <Panel title="Recommendations">
            <ul className="grid gap-2">
              {r.recommendations.map((t, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-ink-2">
                  {t}
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Cost forecast" note="Illustrative part and repair costs from the model assumptions; not a quote.">
            <dl className="grid gap-1.5 text-[12px]">
              <CostRow label="Expected wear replacements" value={r.cost_forecast.expected_wear_replacement_cost} />
              <CostRow label="Expected repairs per race" value={r.cost_forecast.expected_repair_cost_per_race} />
              <CostRow label="Total" value={r.cost_forecast.total} strong />
            </dl>
          </Panel>
        </div>
      </div>

      <Panel title="Closest calls" subtitle={`The ${Math.min(r.close_calls.length, 20)} races with the lowest time to collision between any two cars in the field — not only this car. Replay one to see who was involved.`}>
        <DataTable columns={closeCols} rows={r.close_calls} rowKey={(c) => c.run_id} compact empty="No race dropped below the critical TTC threshold." />
      </Panel>

      <Caveat>{r.note}</Caveat>
    </div>
  );
}

function CostRow({ label, value, strong }: { label: string; value: number; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-3 ${strong ? "border-t border-line pt-1.5" : ""}`}>
      <dt className={strong ? "text-ink" : "text-ink-3"}>{label}</dt>
      <dd className={`num ${strong ? "font-semibold text-ink" : "text-ink-2"}`}>{dec(value, 0)}</dd>
    </div>
  );
}

/**
 * One row per part: min–max range bar, median dot, current-condition tick.
 * Single series, so no legend; values are printed on every row so the chart
 * doubles as its own table.
 */
function WearChart({ parts }: { parts: StressPartReport[] }) {
  return (
    <div role="table" aria-label="Predicted life used per part">
      <div role="row" className="grid grid-cols-[minmax(140px,1fr)_2.2fr_120px_auto] gap-3 border-b border-line-strong pb-1.5">
        <span role="columnheader" className="label-xs !text-[9.5px]">Part</span>
        <span role="columnheader" className="label-xs !text-[9.5px]">0 — 100%</span>
        <span role="columnheader" className="label-xs !text-[9.5px] text-right">Median (range)</span>
        <span role="columnheader" className="label-xs !text-[9.5px] text-right">Status</span>
      </div>
      {parts.map((p) => {
        const lo = Math.max(0, Math.min(100, p.predicted_min_pct));
        const hi = Math.max(0, Math.min(100, p.predicted_max_pct));
        const med = Math.max(0, Math.min(100, p.predicted_median_pct));
        const now = Math.max(0, Math.min(100, p.current_life_used_pct));
        const tip =
          `${partLabel(p.part)}\nToday ${dec(p.current_life_used_pct, 1)}%\n` +
          `Median ${dec(p.predicted_median_pct, 1)}% (range ${dec(p.predicted_min_pct, 1)}–${dec(p.predicted_max_pct, 1)}%)\n` +
          `Crossed 90% in ${p.races_crossing_red}/${p.races_evaluated} races`;
        return (
          <div key={p.part} role="row" title={tip} className="grid grid-cols-[minmax(140px,1fr)_2.2fr_120px_auto] items-center gap-3 border-b border-line/60 py-2.5 last:border-0 hover:bg-surface-2/50">
            <span role="cell" className="truncate text-[12px] text-ink-2">{partLabel(p.part)}</span>
            <span role="cell" className="relative block h-[14px]">
              <span className="absolute inset-x-0 top-1/2 h-[2px] -translate-y-1/2 rounded-full bg-surface-3" />
              {[AMBER, RED].map((t) => (
                <span key={t} className="absolute inset-y-0 w-[1px] bg-[color:var(--text-muted)]" style={{ left: `${t}%` }} aria-hidden />
              ))}
              <span
                className="absolute top-1/2 h-[6px] -translate-y-1/2 rounded-full"
                style={{ left: `${lo}%`, width: `${Math.max(hi - lo, 0.6)}%`, background: "var(--accent)", opacity: 0.45 }}
              />
              <span
                className="absolute top-1/2 h-[12px] w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[color:var(--text-secondary)]"
                style={{ left: `${now}%` }}
                aria-hidden
              />
              <span
                className="absolute top-1/2 h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
                style={{ left: `${med}%`, background: "var(--accent)", borderColor: "var(--surface-1)" }}
              />
            </span>
            <span role="cell" className="num text-right text-[12px] text-ink">
              {dec(p.predicted_median_pct, 1)}%{" "}
              <span className="text-[10.5px] text-ink-3">
                ({dec(p.predicted_min_pct, 0)}–{dec(p.predicted_max_pct, 0)})
              </span>
            </span>
            <span role="cell" className="flex justify-end">
              <PartStatusBadge status={p.status} />
            </span>
          </div>
        );
      })}
    </div>
  );
}
