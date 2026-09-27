"use client";

import { ArrowRight, Loader2, Play, Send, Sparkles, Zap } from "lucide-react";
import Link from "next/link";
import React from "react";

import { api, AskResponse, JobSnapshot, Pattern } from "../lib/api";
import { dec, int, outOf, pct, sec, titleCase } from "../lib/format";
import { useApp } from "../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_LABEL,
  ERROR_LABEL,
  SEVERITY,
  TRAFFIC_BAND_LABEL,
  WEATHER_LABEL,
} from "../lib/theme";
import { Badge, Button, Caveat, EmptyState, ErrorState, Panel, Select } from "./ui";

/* ------------------------------------------------------------ PageHeader --- */

export function PageHeader({
  title,
  lede,
  right,
}: {
  title: string;
  lede?: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 max-w-3xl">
        <h1 className="text-[19px] font-semibold leading-tight tracking-tight text-ink">
          {title}
        </h1>
        {lede && <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-3">{lede}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

/* ----------------------------------------------------------- RequireBatch --- */

export function RequireBatch({ children }: { children: React.ReactNode }) {
  const { batchId, loading, apiOnline, metaError } = useApp();
  if (apiOnline === false) {
    return (
      <ErrorState
        error={
          metaError instanceof Error
            ? metaError
            : new Error("The simulation API is not reachable.")
        }
      />
    );
  }
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-10 text-ink-3">
        <Loader2 size={14} className="animate-spin" aria-hidden />
        <span className="text-xs">Connecting to the simulation engine…</span>
      </div>
    );
  }
  if (!batchId) {
    return (
      <EmptyState
        title="No completed batch yet"
        body="Every figure in this application comes from simulation runs, so there is nothing to show until a batch has been executed. Run a stress test to generate one."
        action={
          <Link href="/">
            <Button variant="primary">
              <Play size={12} /> Go to Overview and run a stress test
            </Button>
          </Link>
        }
      />
    );
  }
  return <>{children}</>;
}

/* --------------------------------------------------------- SeverityBadge --- */

export function SeverityBadge({ severity }: { severity: string }) {
  const s = SEVERITY[severity as keyof typeof SEVERITY];
  if (!s) return <Badge>{severity}</Badge>;
  return (
    <Badge color={s.color} glyph={s.glyph} title={s.description}>
      {s.label}
    </Badge>
  );
}

export function SeverityLegend() {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1">
      {(["NORMAL", "WARNING", "CRITICAL", "INCIDENT"] as const).map((k) => {
        const s = SEVERITY[k];
        return (
          <li key={k} className="flex items-center gap-1.5" title={s.description}>
            <span className="num text-[11px]" style={{ color: s.color }} aria-hidden>
              {s.glyph}
            </span>
            <span className="text-[10.5px] text-ink-3">{s.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------ PatternCard --- */

export function PatternCard({
  pattern,
  onReplay,
  compact = false,
}: {
  pattern: Pattern;
  onReplay?: (runId: string) => void;
  compact?: boolean;
}) {
  const p = pattern;
  const c = p.conditions ?? ({} as Pattern["conditions"]);
  const topPair = c.dominant_archetype_pairs?.[0];
  const topError = c.dominant_errors?.[0];

  return (
    <article className="rounded-md border border-line bg-surface-1/90">
      <header className="flex items-start justify-between gap-3 border-b border-line px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="num shrink-0 rounded bg-surface-3 px-1.5 py-[2px] text-[10.5px] text-ink-2">
            #{p.rank}
          </span>
          <h3 className="truncate text-[13px] font-medium text-ink">
            {p.location}
          </h3>
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-[15px] font-medium text-ink">
            {outOf(p.occurrences, p.runs_evaluated)}
          </div>
          <div className="text-[9.5px] text-ink-3">simulated runs with this pattern</div>
          {p.band_runs && p.occurrence_rate !== null ? (
            <div
              className="mt-0.5 text-[9.5px] text-ink-3"
              title={
                "A raw count also reflects how often this weather and traffic band was " +
                "sampled. Within the runs that were actually drawn in this band, the " +
                "pattern appeared at this rate — the fairer comparison between patterns."
              }
            >
              <span className="num text-ink-2">{pct(p.occurrence_rate, 1)}</span> of the{" "}
              <span className="num">{int(p.band_runs)}</span> comparable runs
            </div>
          ) : null}
        </div>
      </header>

      <div className="px-3 py-2.5">
        <div className="flex flex-wrap gap-1.5">
          <Badge>{WEATHER_LABEL[p.weather] ?? p.weather}</Badge>
          <Badge>{TRAFFIC_BAND_LABEL[p.traffic_band] ?? p.traffic_band}</Badge>
          <Badge>{CONFLICT_TYPE_LABEL[p.conflict_type] ?? p.conflict_type}</Badge>
          <Badge>{int(p.n_cars)} cars</Badge>
        </div>

        <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
          <Metric label="Median min TTC" value={sec(p.median_min_ttc)} />
          <Metric label="5th pct min TTC" value={sec(p.p05_min_ttc)} />
          <Metric label="Median min PET" value={p.median_min_pet === null ? "—" : sec(p.median_min_pet)} />
          <Metric label="Median closing" value={`${dec(p.median_closing_speed, 1)} m/s`} />
          <Metric label="Evasive action" value={pct(p.evasive_rate, 0)} />
          <Metric label="Ended in contact" value={pct(p.collision_rate, 0)} />
          <Metric label="Peak decel (median)" value={`${dec(c.median_max_deceleration_g, 1)} g`} />
          <Metric label="Mean SCSI" value={dec(p.mean_scsi, 3)} hint="Constructed ranking index — see Model Assumptions." />
        </dl>

        {!compact && (
          <div className="mt-2.5 space-y-1.5 border-t border-line pt-2.5">
            {topPair && (
              <p className="text-[11.5px] leading-relaxed text-ink-3">
                <span className="text-ink-2">Most common pairing:</span>{" "}
                {ARCHETYPE_SHORT[topPair.pair[0]] ?? topPair.pair[0]} +{" "}
                {ARCHETYPE_SHORT[topPair.pair[1]] ?? topPair.pair[1]}{" "}
                <span className="num">
                  ({topPair.count} of {c.conflict_instances} instances,{" "}
                  {pct(topPair.share, 0)})
                </span>
                {topPair.share < 0.3 && (
                  <span className="text-ink-3">
                    {" "}
                    — a minority share, so the pairing characterises rather than
                    defines this pattern.
                  </span>
                )}
              </p>
            )}
            {topError && (
              <p className="text-[11.5px] leading-relaxed text-ink-3">
                <span className="text-ink-2">Most common human error:</span>{" "}
                {ERROR_LABEL[topError.error] ?? titleCase(topError.error)}{" "}
                <span className="num">({pct(topError.share, 0)} of instances)</span>
              </p>
            )}
            {c.corner_radius && (
              <p className="text-[11.5px] leading-relaxed text-ink-3">
                <span className="text-ink-2">Zone geometry:</span>{" "}
                {dec(c.corner_radius, 0)} m radius, narrowest point{" "}
                {dec(c.zone_min_width, 1)} m, {dec(c.runoff_width, 0)} m runoff,
                overtaking rating {dec(c.overtaking_opportunity, 2)}
              </p>
            )}
          </div>
        )}

        {onReplay && p.example_run_ids?.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1.5 border-t border-line pt-2.5">
            <Button size="sm" variant="primary" onClick={() => onReplay(p.example_run_ids[0])}>
              Replay an example <ArrowRight size={11} />
            </Button>
            <span className="self-center text-[10px] text-ink-3">
              {p.example_run_ids.length} example run
              {p.example_run_ids.length === 1 ? "" : "s"} retained
            </span>
          </div>
        )}
      </div>
    </article>
  );
}

export function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="min-w-0" title={hint}>
      <dt className="label-xs !text-[9px]">{label}</dt>
      <dd className="num mt-[2px] truncate text-[12.5px] text-ink">{value}</dd>
    </div>
  );
}

/* ------------------------------------------------------ StressTestLauncher --- */

export function StressTestLauncher() {
  const { watchJob, jobs, meta } = useApp();
  const [runs, setRuns] = React.useState("2000");
  const [mode, setMode] = React.useState<"monte_carlo" | "guided">("monte_carlo");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);

  const active = jobs.find((j) => j.status === "running");

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const job =
        mode === "monte_carlo"
          ? await api.startBatch({
              n_runs: Number(runs),
              label: `Monte Carlo search × ${int(Number(runs))}`,
              replay_budget: 400,
            })
          : await api.startGuided({
              generations: 8,
              population: Math.max(20, Math.round(Number(runs) / 8)),
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
    <Panel
      title="Run stress test"
      subtitle="Generate and execute a fresh scenario population."
      right={
        <span className="num text-[10.5px] text-ink-3">
          {meta ? `${meta.tracks.length} circuits · ${meta.archetypes.length} archetypes` : ""}
        </span>
      }
    >
      {err ? <ErrorState error={err} /> : null}
      <div className="flex flex-wrap items-end gap-2.5">
        <Select
          label="Search strategy"
          value={mode}
          onChange={(v) => setMode(v as typeof mode)}
          className="w-[190px]"
          options={[
            { value: "monte_carlo", label: "Random Monte Carlo" },
            { value: "guided", label: "Guided (adversarial)" },
          ]}
        />
        <Select
          label={mode === "monte_carlo" ? "Simulations" : "Approx. total runs"}
          value={runs}
          onChange={setRuns}
          className="w-[150px]"
          options={[
            { value: "200", label: "200 — quick" },
            { value: "600", label: "600" },
            { value: "2000", label: "2,000 — default" },
            { value: "5000", label: "5,000" },
            { value: "10000", label: "10,000 — full" },
          ]}
        />
        <Button variant="primary" onClick={start} disabled={busy || !!active}>
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
          {active ? "A batch is already running" : "Run stress test"}
        </Button>
      </div>

      {active && <JobProgress job={active} />}

      <Caveat>
        {mode === "monte_carlo"
          ? "Random search samples the whole scenario space uniformly and establishes the baseline."
          : "Guided search keeps the scenarios that produced severe conflicts and mutates around them. It finds severe regions faster; it does not make them more likely in reality."}
      </Caveat>
    </Panel>
  );
}

export function JobProgress({ job }: { job: JobSnapshot }) {
  const frac = job.total ? Math.min(job.completed / job.total, 1) : 0;
  const latest = job.latest ?? {};
  return (
    <div className="mt-3 rounded border border-line bg-surface-2/60 px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
          {job.status === "running" && (
            <Loader2 size={11} className="animate-spin" aria-hidden />
          )}
          {job.label}
          <span className="text-ink-3">· {job.phase}</span>
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
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {[
          ["conflicts", "Conflicts"],
          ["critical", "Critical"],
          ["collisions", "Collisions"],
          ["near_misses", "Near misses"],
        ].map(([k, label]) =>
          latest[k] === undefined ? null : (
            <span key={k} className="text-[10.5px] text-ink-3">
              {label} <span className="num text-ink-2">{int(Number(latest[k]))}</span>
            </span>
          )
        )}
        <span className="text-[10.5px] text-ink-3">
          Rate <span className="num text-ink-2">{dec(job.runs_per_second, 1)}</span> runs/s
        </span>
        {job.error && (
          <span className="text-[10.5px]" style={{ color: "var(--critical)" }}>
            {job.error}
          </span>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- AskPanel --- */

export function AskPanel({ batchId }: { batchId: string }) {
  const { meta } = useApp();
  const [q, setQ] = React.useState("");
  const [res, setRes] = React.useState<AskResponse | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);
  const [showQueries, setShowQueries] = React.useState(false);

  const submit = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.ask(batchId, question));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const suggestions = meta?.query_suggestions ?? [];

  return (
    <Panel
      title="Ask the simulator"
      subtitle="Questions are answered from fixed SQL queries against this batch's stored results — never from a model's recollection."
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(q);
        }}
        className="flex gap-2"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Why is Turn 7 a hotspot?"
          aria-label="Question about this batch"
          className="min-w-0 flex-1 rounded border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[12px] text-ink placeholder:text-ink-3 hover:border-[color:var(--accent)]"
        />
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          Ask
        </Button>
      </form>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {suggestions.slice(0, 6).map((s) => (
          <button
            key={s}
            onClick={() => {
              setQ(s);
              submit(s);
            }}
            className="rounded border border-line px-1.5 py-[3px] text-[10.5px] text-ink-3 hover:border-line-strong hover:text-ink-2"
          >
            {s}
          </button>
        ))}
      </div>

      {err ? (
        <div className="mt-3">
          <ErrorState error={err} />
        </div>
      ) : null}

      {res && (
        <div className="fade-up mt-3 rounded border border-line bg-surface-2/50 px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            <Sparkles size={11} className="text-ink-3" aria-hidden />
            <span className="label-xs">{res.intent_description}</span>
          </div>
          {res.error ? (
            <p className="mt-1.5 text-[12px]" style={{ color: "var(--critical)" }}>
              {res.error}
            </p>
          ) : (
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">{res.answer}</p>
          )}
          {res.queries && res.queries.length > 0 && (
            <div className="mt-2 border-t border-line pt-2">
              <button
                onClick={() => setShowQueries((s) => !s)}
                className="text-[10.5px] text-ink-3 underline decoration-dotted hover:text-ink-2"
              >
                {showQueries ? "Hide" : "Show"} the query behind this answer
              </button>
              {showQueries && (
                <pre className="mt-1.5 overflow-x-auto rounded bg-plane/70 p-2 font-mono text-[10px] leading-relaxed text-ink-3">
                  {res.queries.map((query) => `${query.sql}\n-- params: ${JSON.stringify(query.params)}`).join("\n\n")}
                </pre>
              )}
            </div>
          )}
          <p className="mt-2 text-[10px] leading-relaxed text-ink-3">{res.provenance}</p>
        </div>
      )}
    </Panel>
  );
}
