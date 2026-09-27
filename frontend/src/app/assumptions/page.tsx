"use client";

import { BookOpen, ExternalLink, Search } from "lucide-react";
import React from "react";

import { Metric, PageHeader } from "../../components/Common";
import {
  Badge,
  Caveat,
  ErrorState,
  Panel,
  SegmentedControl,
  Skeleton,
  StatTile,
} from "../../components/ui";
import { api, Assumption } from "../../lib/api";
import { dec, int } from "../../lib/format";
import { useFetch } from "../../lib/store";

type Filter = "all" | "methodology" | "assumption";

export default function AssumptionsPage() {
  const a = useFetch(() => api.assumptions(), []);
  const [filter, setFilter] = React.useState<Filter>("all");
  const [query, setQuery] = React.useState("");

  const filtered = React.useMemo(() => {
    const items = a.data?.assumptions ?? [];
    const q = query.trim().toLowerCase();
    return items.filter(
      (it) =>
        (filter === "all" || it.kind === filter) &&
        (!q ||
          it.label.toLowerCase().includes(q) ||
          it.key.toLowerCase().includes(q) ||
          it.note.toLowerCase().includes(q) ||
          it.group.toLowerCase().includes(q))
    );
  }, [a.data, filter, query]);

  const groups = React.useMemo(() => {
    const m = new Map<string, Assumption[]>();
    for (const it of filtered) {
      if (!m.has(it.group)) m.set(it.group, []);
      m.get(it.group)!.push(it);
    }
    return [...m.entries()];
  }, [filtered]);

  return (
    <>
      <PageHeader
        title="Model assumptions"
        lede="Every tunable number in the simulator, in one place, each labelled with what sort of claim it represents. This page exists so a reader can see exactly which dials produced the results elsewhere in the application."
      />

      {a.loading && !a.data ? (
        <Skeleton h={400} />
      ) : a.error ? (
        <ErrorState error={a.error} onRetry={a.reload} />
      ) : a.data ? (
        <>
          {/* ------------------------------------------ the four categories --- */}
          <Panel
            title="What this application does and does not claim"
            className="mb-3"
          >
            <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  title: "Established methodology",
                  body:
                    "Time-to-collision and post-encroachment time are established surrogate safety measures, used here with SSAM's conflict thresholds and conflict-typing scheme. The concepts are external and cited.",
                  tone: "var(--series-3)",
                  count: a.data.counts.methodology,
                },
                {
                  title: "Simulation assumptions",
                  body:
                    "The driver parameters, error rates, vehicle limits and decision thresholds are choices made by this prototype. They are not measured, not validated, and changing them changes every result.",
                  tone: "var(--warning)",
                  count: a.data.counts.assumption,
                },
                {
                  title: "Simulation results",
                  body:
                    "The conflict counts, recurrence figures and hotspot rankings are outputs of this model under those assumptions. They describe the model's behaviour.",
                  tone: "var(--series-1)",
                  count: null,
                },
                {
                  title: "Real-world claims",
                  body:
                    "There are none. No figure in this application is a crash probability, an incident rate, or an assessment of a real circuit, driver or series. No validation against recorded incident data has been performed.",
                  tone: "var(--critical)",
                  count: 0,
                },
              ].map((c) => (
                <div
                  key={c.title}
                  className="rounded border-l-2 border border-line bg-surface-2/40 px-3 py-2.5"
                  style={{ borderLeftColor: c.tone }}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-[12px] font-semibold text-ink">{c.title}</p>
                    {c.count !== null && (
                      <span className="num text-[11px]" style={{ color: c.tone }}>
                        {int(c.count)}
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-3">{c.body}</p>
                </div>
              ))}
            </div>
          </Panel>

          {/* ---------------------------------------------------- the index --- */}
          <div className="mb-3 grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <StatTile label="Total parameters" value={int(a.data.counts.total)} />
            <StatTile
              label="From methodology"
              value={int(a.data.counts.methodology)}
              tone="good"
              sub="concept taken from external practice"
            />
            <StatTile
              label="Prototype assumptions"
              value={int(a.data.counts.assumption)}
              tone="warning"
              sub="not measured, not validated"
            />
            <StatTile label="Groups" value={int(a.data.groups.length)} />
          </div>

          <div className="mb-3 flex flex-wrap items-end gap-3 rounded-md border border-line bg-surface-1/80 px-3 py-2.5">
            <SegmentedControl
              label="Show"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "All" },
                { value: "methodology", label: "Methodology" },
                { value: "assumption", label: "Assumptions" },
              ]}
              size="sm"
            />
            <label className="flex flex-1 flex-col gap-1">
              <span className="label-xs">Search</span>
              <span className="relative">
                <Search
                  size={12}
                  className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-3"
                  aria-hidden
                />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="grip, reaction, TTC threshold…"
                  className="w-full rounded border border-line-strong bg-surface-2 py-[5px] pl-7 pr-2 text-[11.5px] text-ink placeholder:text-ink-3"
                />
              </span>
            </label>
            <span className="num self-end text-[11px] text-ink-3">
              {int(filtered.length)} shown
            </span>
          </div>

          <Caveat tone="strong">{a.data.provenance_note}</Caveat>

          {/* ---------------------------------------------------- the SCSI --- */}
          <div className="mt-3">
            <Panel
              title="Simulation Conflict Severity Index"
              subtitle="Shown here in full because it is the one composite figure in the application."
            >
              <p className="text-[12.5px] leading-relaxed text-ink-2">
                {a.data.scsi.definition}
              </p>
              <div className="mt-2.5 flex flex-wrap gap-2.5 border-t border-line pt-2.5">
                {Object.entries(a.data.scsi.weights).map(([k, v]) => (
                  <div key={k} className="rounded border border-line bg-surface-2/40 px-2.5 py-1.5">
                    <div className="label-xs !text-[9px]">{k.replace(/_/g, " ")}</div>
                    <div className="num text-[13px] text-ink">{dec(v, 2)}</div>
                  </div>
                ))}
                <div className="rounded border border-line bg-surface-2/40 px-2.5 py-1.5">
                  <div className="label-xs !text-[9px]">closing speed reference</div>
                  <div className="num text-[13px] text-ink">
                    {dec(a.data.scsi.closing_speed_ref, 0)} m/s
                  </div>
                </div>
                <div className="rounded border border-line bg-surface-2/40 px-2.5 py-1.5">
                  <div className="label-xs !text-[9px]">deceleration reference</div>
                  <div className="num text-[13px] text-ink">
                    {dec(a.data.scsi.decel_ref, 0)} m/s²
                  </div>
                </div>
              </div>
              <Caveat>
                Wherever this index appears in the application, the raw surrogate metrics
                appear beside it, and every ranked view can be switched to raw minimum
                TTC instead.
              </Caveat>
            </Panel>
          </div>

          {/* ------------------------------------------------- the registry --- */}
          <div className="mt-3 grid gap-3">
            {groups.map(([group, items]) => (
              <Panel key={group} title={group} subtitle={`${items.length} parameters`}>
                <ul className="divide-y divide-line">
                  {items.map((it) => (
                    <li key={it.key} className="py-2.5 first:pt-0 last:pb-0">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="flex min-w-0 flex-wrap items-baseline gap-2">
                          <span className="text-[12.5px] font-medium text-ink">{it.label}</span>
                          <span className="num text-[10px] text-ink-3">{it.key}</span>
                          <Badge
                            color={
                              it.kind === "methodology" ? "var(--series-3)" : "var(--warning)"
                            }
                            glyph={it.kind === "methodology" ? "✓" : "△"}
                          >
                            {it.kind}
                          </Badge>
                        </span>
                        <span className="num shrink-0 text-[12.5px] text-ink">
                          {formatValue(it.value)}
                          {it.unit && (
                            <span className="ml-1 text-[10px] text-ink-3">{it.unit}</span>
                          )}
                        </span>
                      </div>
                      {it.note && (
                        <p className="mt-1 max-w-4xl text-[11.5px] leading-relaxed text-ink-3">
                          {it.note}
                        </p>
                      )}
                      <div className="mt-1 flex flex-wrap gap-3">
                        {it.reference && (
                          <span className="flex items-center gap-1 text-[10px] text-ink-3">
                            <BookOpen size={10} aria-hidden />
                            {it.reference}
                          </span>
                        )}
                        {it.range && (
                          <span className="num text-[10px] text-ink-3">
                            tunable range {it.range[0]} – {it.range[1]}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </Panel>
            ))}
          </div>

          {/* ------------------------------------------------- references --- */}
          <div className="mt-3">
            <Panel
              title="Methodological references"
              subtitle="The external practice this prototype builds on."
            >
              <ul className="space-y-1.5">
                {a.data.references.map((r) => (
                  <li key={r.url}>
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-baseline gap-1.5 text-[12px] text-ink-2 hover:text-ink"
                    >
                      <ExternalLink size={11} className="mt-[2px] shrink-0 text-ink-3" aria-hidden />
                      <span>
                        {r.label}
                        <span className="ml-1.5 break-all font-mono text-[10px] text-ink-3">
                          {r.url}
                        </span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
              <Caveat>
                Professional motorsport organisations already perform circuit safety
                analysis and driver-in-the-loop simulation at far higher fidelity than
                anything here. These references are the methodology this prototype
                borrows from; citing them is not a claim of equivalence with them.
              </Caveat>
            </Panel>
          </div>
        </>
      ) : null}
    </>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : v.toFixed(v < 0.01 ? 5 : 3).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>);
    if (entries.length <= 4)
      return entries.map(([k, x]) => `${k}: ${formatValue(x)}`).join(", ");
    return `${entries.length} entries`;
  }
  return String(v);
}
