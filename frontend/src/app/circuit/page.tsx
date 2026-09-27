"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import React from "react";

import { BarChart, HBarChart, RampLegend } from "../../components/charts";
import { CircuitMap, conflictMarkers } from "../../components/CircuitMap";
import {
  Metric,
  PageHeader,
  RequireBatch,
  SeverityBadge,
  SeverityLegend,
} from "../../components/Common";
import {
  Button,
  Caveat,
  Column,
  DataTable,
  ErrorState,
  KeyValue,
  Panel,
  SegmentedControl,
  Skeleton,
  Toggle,
} from "../../components/ui";
import { api, ConflictRow, HotspotSegment } from "../../lib/api";
import { dec, int, metres, sec, titleCase } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";
import {
  ARCHETYPE_SHORT,
  CONFLICT_TYPE_COLOR,
  CONFLICT_TYPE_LABEL,
  ERROR_LABEL,
  WEATHER_COLOR,
  WEATHER_LABEL,
  WEATHER_ORDER,
} from "../../lib/theme";

type MetricKey =
  | "conflicts"
  | "conflicts_per_run"
  | "critical"
  | "collisions"
  | "median_min_ttc"
  | "density";

const METRICS: { value: MetricKey; label: string; title: string }[] = [
  { value: "conflicts", label: "Conflicts", title: "Total conflicts detected in this segment" },
  { value: "conflicts_per_run", label: "Per run", title: "Conflicts per simulated run" },
  { value: "critical", label: "Critical", title: "Conflicts classified critical" },
  { value: "collisions", label: "Contacts", title: "Conflicts that ended in contact" },
  {
    value: "median_min_ttc",
    label: "Severity (1/TTC)",
    title:
      "Inverse of median minimum TTC — higher means the conflicts there came closer",
  },
  {
    value: "density",
    label: "Per 100 m",
    title: "Conflicts per run per 100 m, which corrects for segment length",
  },
];

export default function CircuitPage() {
  return (
    <RequireBatch>
      <CircuitAnalysis />
    </RequireBatch>
  );
}

function CircuitAnalysis() {
  const { batchId, track } = useApp();
  const router = useRouter();
  const [metric, setMetric] = React.useState<MetricKey>("conflicts");
  const [selected, setSelected] = React.useState<number | null>(null);
  const [showMarkers, setShowMarkers] = React.useState(true);
  const [severityFilter, setSeverityFilter] = React.useState("");
  const [weatherFilter, setWeatherFilter] = React.useState("");
  const [typeFilter, setTypeFilter] = React.useState("");
  const [maxTtc, setMaxTtc] = React.useState("");

  const hs = useFetch(batchId ? () => api.hotspots(batchId) : null, [batchId]);
  const detail = useFetch(
    batchId && selected !== null ? () => api.hotspotDetail(batchId, selected) : null,
    [batchId, selected]
  );
  const conflicts = useFetch(
    batchId
      ? () =>
          api.conflicts({
            batch_id: batchId,
            severity: severityFilter || undefined,
            weather: weatherFilter || undefined,
            conflict_type: typeFilter || undefined,
            max_ttc: maxTtc || undefined,
            limit: 700,
          })
      : null,
    [batchId, severityFilter, weatherFilter, typeFilter, maxTtc]
  );

  const values = React.useMemo(() => {
    if (!hs.data) return {} as Record<number, number>;
    const out: Record<number, number> = {};
    for (const s of hs.data.segments) {
      let v = 0;
      if (metric === "conflicts") v = s.conflicts;
      else if (metric === "conflicts_per_run") v = s.conflicts_per_run;
      else if (metric === "critical") v = s.critical;
      else if (metric === "collisions") v = s.collisions;
      else if (metric === "density") v = s.conflicts_per_100m_per_run;
      else if (metric === "median_min_ttc")
        v = s.median_min_ttc && s.median_min_ttc > 0 ? 1 / s.median_min_ttc : 0;
      out[s.segment_index] = v;
    }
    return out;
  }, [hs.data, metric]);

  const markers = React.useMemo(() => {
    if (!showMarkers || !track || !conflicts.data) return [];
    return conflictMarkers(track, conflicts.data.conflicts.slice(0, 500));
  }, [showMarkers, track, conflicts.data]);

  const seg = detail.data?.detail.segment;
  const metricFmt = (v: number) =>
    metric === "conflicts_per_run" || metric === "density"
      ? dec(v, 3)
      : dec(v, metric === "median_min_ttc" ? 2 : 0);

  return (
    <>
      <PageHeader
        title="Circuit analysis"
        lede="Where conflicts occurred, and why this model kept producing them there. Click any part of the track — or any row — to open its breakdown."
      />

      <div className="mb-3 flex flex-wrap items-end gap-3 rounded-md border border-line bg-surface-1/80 px-3 py-2.5">
        <SegmentedControl label="Tint by" value={metric} onChange={setMetric} options={METRICS} size="sm" />
        <FilterSelect
          label="Severity"
          value={severityFilter}
          onChange={setSeverityFilter}
          options={[
            { value: "", label: "All" },
            { value: "WARNING", label: "Warning" },
            { value: "CRITICAL", label: "Critical" },
            { value: "INCIDENT", label: "Incident" },
          ]}
        />
        <FilterSelect
          label="Weather"
          value={weatherFilter}
          onChange={setWeatherFilter}
          options={[
            { value: "", label: "All" },
            ...WEATHER_ORDER.map((w) => ({ value: w, label: WEATHER_LABEL[w] })),
          ]}
        />
        <FilterSelect
          label="Conflict type"
          value={typeFilter}
          onChange={setTypeFilter}
          options={[
            { value: "", label: "All" },
            ...Object.entries(CONFLICT_TYPE_LABEL).map(([k, v]) => ({ value: k, label: v })),
          ]}
        />
        <FilterSelect
          label="Max TTC"
          value={maxTtc}
          onChange={setMaxTtc}
          options={[
            { value: "", label: "Any" },
            { value: "1.0", label: "≤ 1.0 s" },
            { value: "0.8", label: "≤ 0.8 s" },
            { value: "0.5", label: "≤ 0.5 s" },
            { value: "0.25", label: "≤ 0.25 s" },
          ]}
        />
        <Toggle
          label="Show conflict points"
          checked={showMarkers}
          onChange={setShowMarkers}
          hint="Each marker sits in the segment where that conflict's TTC bottomed out. Its exact position within the segment is illustrative, not the recorded coordinate."
        />
        {selected !== null && (
          <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
            Clear selection
          </Button>
        )}
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Panel
          title={
            track
              ? `${track.name} — ${dec(track.length, 0)} m, ${
                  track.segments.filter((s) => s.turn_number !== null && s.corner_radius !== null)
                    .length
                } numbered corners`
              : "Circuit"
          }
          subtitle={METRICS.find((m) => m.value === metric)?.title}
          note={hs.data?.note}
        >
          {hs.loading && !hs.data ? (
            <Skeleton h={440} />
          ) : hs.error ? (
            <ErrorState error={hs.error} onRetry={hs.reload} />
          ) : hs.data && track ? (
            <>
              <CircuitMap
                track={track}
                height={440}
                segmentValues={values}
                onSegmentClick={setSelected}
                selectedSegment={selected}
                markers={markers}
                focusSegment={selected}
              />
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-3">
                <RampLegend
                  max={Math.max(...Object.values(values), 0)}
                  label={METRICS.find((m) => m.value === metric)?.label}
                  format={metricFmt}
                />
                <SeverityLegend />
              </div>
              <Caveat>
                Track width is drawn to scale, so a narrow corner looks narrow. The
                dotted line is the nominal racing line the agents target.
              </Caveat>
            </>
          ) : null}
        </Panel>

        <div className="flex min-w-0 flex-col gap-3">
          {selected === null ? (
            <>
              <Panel title="Segments ranked" subtitle="Click a row to open its breakdown.">
                {hs.data ? (
                  <DataTable<HotspotSegment>
                    rows={[...hs.data.segments].sort((a, b) => b.conflicts - a.conflicts)}
                    rowKey={(r) => String(r.segment_index)}
                    onRowClick={(r) => setSelected(r.segment_index)}
                    maxHeight={340}
                    compact
                    columns={segmentColumns}
                  />
                ) : (
                  <Skeleton h={340} />
                )}
              </Panel>
              <Panel
                title="Corner geometry against conflict rate"
                subtitle="Every numbered corner, by conflicts per run."
              >
                {hs.data ? (
                  <HBarChart
                    data={hs.data.segments
                      .filter((s) => s.turn_number !== null && s.corner_radius !== null)
                      .sort((a, b) => b.conflicts_per_run - a.conflicts_per_run)
                      .map((s) => ({
                        key: String(s.segment_index),
                        label: `T${s.turn_number} · ${dec(s.width, 1)} m wide`,
                        value: s.conflicts_per_run,
                        tip: [
                          { label: "Radius", value: metres(s.corner_radius, 0) },
                          { label: "Width", value: metres(s.width, 1) },
                          { label: "Runoff", value: metres(s.runoff_width, 0) },
                          { label: "Speed ceiling", value: `${dec(s.target_speed_kph, 0)} km/h` },
                          { label: "Conflicts / run", value: dec(s.conflicts_per_run, 3) },
                          { label: "Median min TTC", value: sec(s.median_min_ttc) },
                        ],
                      }))}
                    labelWidth={136}
                    valueFormat={(v) => dec(v, 3)}
                    onSelect={(d) => setSelected(Number(d.key))}
                  />
                ) : (
                  <Skeleton h={260} />
                )}
              </Panel>
            </>
          ) : detail.loading && !detail.data ? (
            <Skeleton h={480} />
          ) : detail.error ? (
            <ErrorState error={detail.error} onRetry={detail.reload} />
          ) : detail.data && seg ? (
            <>
              <Panel
                title="Why is this location flagged?"
                subtitle={seg.name}
                right={
                  <span className="num text-[11px] text-ink-3">segment {seg.segment_index}</span>
                }
              >
                <p className="text-[12.5px] leading-relaxed text-ink-2">{detail.data.text}</p>

                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-2.5 sm:grid-cols-3">
                  <Metric label="Conflicts" value={int(seg.conflicts)} />
                  <Metric label="Per run" value={dec(seg.conflicts_per_run, 3)} />
                  <Metric label="Critical" value={int(seg.critical)} />
                  <Metric label="Contacts" value={int(seg.collisions)} />
                  <Metric label="Evasive" value={int(seg.evasive)} />
                  <Metric label="Median min TTC" value={sec(seg.median_min_ttc)} />
                  <Metric label="5th pct min TTC" value={sec(seg.p05_min_ttc)} />
                  <Metric label="Median min PET" value={sec(seg.median_min_pet)} />
                  <Metric label="Median closing" value={`${dec(seg.median_closing_speed, 1)} m/s`} />
                </div>

                <div className="mt-3 border-t border-line pt-2.5">
                  <KeyValue
                    cols={3}
                    rows={[
                      { label: "Type", value: titleCase(seg.type) },
                      { label: "Length", value: metres(seg.length, 0) },
                      { label: "Width", value: metres(seg.width, 1) },
                      {
                        label: "Radius",
                        value: seg.corner_radius ? metres(seg.corner_radius, 0) : "straight",
                      },
                      { label: "Speed ceiling", value: `${dec(seg.target_speed_kph, 0)} km/h` },
                      { label: "Runoff", value: metres(seg.runoff_width, 0) },
                      { label: "Barrier", value: metres(seg.barrier_distance, 0) },
                      { label: "Overtaking rating", value: dec(seg.overtaking_opportunity, 2) },
                      {
                        label: "Slack for two cars",
                        value: metres(seg.width - 4.0, 1),
                        hint: "Segment width minus two car widths — the lateral room available for a side-by-side pass.",
                      },
                    ]}
                  />
                </div>
              </Panel>

              <Panel title="Conditions under which it was flagged" dense>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="label-xs mb-1.5">By weather</p>
                    <BarChart
                      data={detail.data.detail.weather_contrast
                        .slice()
                        .sort(
                          (a, b) =>
                            WEATHER_ORDER.indexOf(a.band as (typeof WEATHER_ORDER)[number]) -
                            WEATHER_ORDER.indexOf(b.band as (typeof WEATHER_ORDER)[number])
                        )
                        .map((wc) => ({
                          key: wc.band,
                          label: WEATHER_LABEL[wc.band] ?? wc.band,
                          value: wc.conflicts_per_run,
                          color: WEATHER_COLOR[wc.band],
                          tip: [
                            { label: "Runs in this band", value: int(wc.runs) },
                            { label: "Conflicts here", value: int(wc.conflicts) },
                            { label: "Per run", value: dec(wc.conflicts_per_run, 3) },
                          ],
                        }))}
                      height={132}
                      yLabel="conflicts / run"
                      valueFormat={(v) => dec(v, 2)}
                    />
                  </div>
                  <div>
                    <p className="label-xs mb-1.5">By traffic density band</p>
                    <BarChart
                      data={["LOW", "MEDIUM", "HIGH"]
                        .map((b) => detail.data!.detail.density_contrast.find((d) => d.band === b))
                        .filter((d): d is NonNullable<typeof d> => !!d)
                        .map((dc, i) => ({
                          key: dc.band,
                          label: titleCase(dc.band),
                          value: dc.conflicts_per_run,
                          color: `var(--seq-${3 + i})`,
                          tip: [
                            { label: "Runs in this band", value: int(dc.runs) },
                            { label: "Conflicts here", value: int(dc.conflicts) },
                            { label: "Per run", value: dec(dc.conflicts_per_run, 3) },
                          ],
                        }))}
                      height={132}
                      yLabel="conflicts / run"
                      valueFormat={(v) => dec(v, 2)}
                    />
                  </div>
                </div>

                <div className="mt-3 grid gap-3 border-t border-line pt-2.5 sm:grid-cols-2">
                  <div>
                    <p className="label-xs mb-1.5">Conflict type mix</p>
                    <ul className="space-y-1">
                      {Object.entries(seg.conflict_type_mix)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 5)
                        .map(([k, v]) => (
                          <li key={k} className="flex items-center justify-between gap-2">
                            <span className="flex min-w-0 items-center gap-1.5">
                              <span
                                className="inline-block h-[8px] w-[8px] shrink-0 rounded-[1px]"
                                style={{ background: CONFLICT_TYPE_COLOR[k] ?? "var(--series-1)" }}
                                aria-hidden
                              />
                              <span className="truncate text-[11.5px] text-ink-2">
                                {CONFLICT_TYPE_LABEL[k] ?? k}
                              </span>
                            </span>
                            <span className="num text-[11.5px] text-ink">{int(v)}</span>
                          </li>
                        ))}
                    </ul>
                  </div>
                  <div>
                    <p className="label-xs mb-1.5">Most common behavioural pairings</p>
                    <ul className="space-y-1">
                      {seg.top_archetype_pairs.map((p) => (
                        <li key={p.pair.join("|")} className="flex items-center justify-between gap-2">
                          <span className="truncate text-[11.5px] text-ink-2">
                            {ARCHETYPE_SHORT[p.pair[0]] ?? p.pair[0]} ×{" "}
                            {ARCHETYPE_SHORT[p.pair[1]] ?? p.pair[1]}
                          </span>
                          <span className="num text-[11.5px] text-ink">{int(p.count)}</span>
                        </li>
                      ))}
                    </ul>
                    {Object.keys(seg.dominant_errors).length > 0 && (
                      <>
                        <p className="label-xs mb-1.5 mt-2.5">Dominant human errors</p>
                        <ul className="space-y-1">
                          {Object.entries(seg.dominant_errors).map(([k, v]) => (
                            <li key={k} className="flex items-center justify-between gap-2">
                              <span className="truncate text-[11.5px] text-ink-2">
                                {ERROR_LABEL[k] ?? titleCase(k)}
                              </span>
                              <span className="num text-[11.5px] text-ink">{int(v)}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                </div>
              </Panel>

              <Panel
                title="Closest interactions here"
                subtitle="Lowest minimum TTC first. Click a row to replay it."
              >
                <DataTable<ConflictRow>
                  rows={detail.data.detail.worst_conflicts}
                  rowKey={(r, i) => `${r.run_id}-${i}`}
                  onRowClick={(r) => router.push(`/replay?run=${r.run_id}`)}
                  maxHeight={260}
                  compact
                  columns={[
                    {
                      key: "sev",
                      header: "Severity",
                      width: "94px",
                      render: (r) => <SeverityBadge severity={r.severity} />,
                    },
                    {
                      key: "ttc",
                      header: "Min TTC",
                      align: "right",
                      render: (r) => sec(r.min_ttc),
                      sortValue: (r) => r.min_ttc,
                    },
                    { key: "pet", header: "Min PET", align: "right", render: (r) => sec(r.min_pet) },
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
                      key: "go",
                      header: "",
                      width: "26px",
                      render: (r) =>
                        r.has_replay ? (
                          <ArrowRight size={12} className="text-ink-3" aria-hidden />
                        ) : null,
                    },
                  ]}
                />
                <Caveat>
                  Only the most severe runs in a batch retain a stored replay window, so
                  rows without an arrow cannot be replayed.
                </Caveat>
              </Panel>
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}

const segmentColumns: Column<HotspotSegment>[] = [
  {
    key: "name",
    header: "Segment",
    render: (r) => (
      <span className="flex items-center gap-1.5">
        {r.turn_number !== null && (
          <span className="num rounded bg-surface-3 px-1 text-[10px] text-ink-2">
            T{r.turn_number}
          </span>
        )}
        <span className="truncate">{r.name}</span>
      </span>
    ),
    sortValue: (r) => r.name,
  },
  { key: "w", header: "Width", align: "right", render: (r) => dec(r.width, 1), sortValue: (r) => r.width },
  { key: "n", header: "Conflicts", align: "right", render: (r) => int(r.conflicts), sortValue: (r) => r.conflicts },
  { key: "crit", header: "Critical", align: "right", render: (r) => int(r.critical), sortValue: (r) => r.critical },
  { key: "coll", header: "Contact", align: "right", render: (r) => int(r.collisions), sortValue: (r) => r.collisions },
  {
    key: "ttc",
    header: "Med TTC",
    align: "right",
    render: (r) => (r.median_min_ttc === null ? "—" : dec(r.median_min_ttc, 2)),
    sortValue: (r) => r.median_min_ttc ?? 99,
  },
];

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="label-xs">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-line-strong bg-surface-2 px-1.5 py-[5px] text-[11.5px] text-ink hover:border-[color:var(--accent)]"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
