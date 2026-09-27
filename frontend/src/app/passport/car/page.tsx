"use client";

import { Loader2, RotateCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import React from "react";

import { PageHeader } from "../../../components/Common";
import { ConditionBadge, PartRow, RequireCar } from "../../../components/passport";
import {
  Button,
  Column,
  DataTable,
  ErrorState,
  Panel,
  Skeleton,
} from "../../../components/ui";
import { datetime, int } from "../../../lib/format";
import {
  Car,
  EVENT_LABEL,
  HistoryEvent,
  partLabel,
  passportApi,
} from "../../../lib/passport";
import { useFetch } from "../../../lib/store";

export default function PassportPage() {
  return (
    <>
      <PageHeader
        title="Passport"
        lede="The car's current condition and its full recorded history. Every history event is hash-chained to the one before it, so an edit made after the fact is detectable."
      />
      <RequireCar>{(car) => <PassportView key={car.id} car={car} />}</RequireCar>
    </>
  );
}

function PassportView({ car }: { car: Car }) {
  const view = useFetch(() => passportApi.passport(car.id), [car.id]);
  const [replacing, setReplacing] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<unknown>(null);

  const replace = async (part: string) => {
    if (!window.confirm(`Record that ${partLabel(part)} was replaced? This resets it to 0% and is logged permanently.`)) return;
    setReplacing(part);
    setErr(null);
    try {
      await passportApi.replacePart(car.id, part);
      view.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setReplacing(null);
    }
  };

  if (view.error) return <ErrorState error={view.error} onRetry={view.reload} />;
  if (!view.data) return <Skeleton h={320} />;
  const { parts, history, chain_verification: chain, policy_conditions, note } = view.data;

  const historyCols: Column<HistoryEvent>[] = [
    { key: "seq", header: "#", align: "right", width: "40px", render: (e) => e.seq },
    { key: "time", header: "Time", render: (e) => <span className="num">{datetime(e.time)}</span> },
    { key: "type", header: "Event", render: (e) => EVENT_LABEL[e.type] ?? e.type },
    { key: "details", header: "Details", render: (e) => <EventDetails event={e} /> },
    {
      key: "hash",
      header: "Hash",
      render: (e) => (
        <span className="num text-[10.5px] text-ink-3" title={`hash ${e.hash}\nprev ${e.prev_hash}`}>
          {e.hash.slice(0, 10)}…
        </span>
      ),
    },
  ];

  return (
    <div className="grid gap-3">
      {err ? <ErrorState error={err} /> : null}
      <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
        <Panel
          title="Part condition"
          subtitle="Life used per part. Ticks mark the inspect (70%) and replace (90%) thresholds."
        >
          {parts.map((p) => (
            <PartRow
              key={p.name}
              part={p}
              action={
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => replace(p.name)}
                  disabled={replacing !== null || p.life_used_pct === 0}
                  title="Record a replacement"
                >
                  {replacing === p.name ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
                  Replace
                </Button>
              }
            />
          ))}
        </Panel>

        <div className="grid content-start gap-3">
          <Panel title="History chain">
            <div className="flex items-start gap-2.5">
              {chain.valid ? (
                <ShieldCheck size={20} style={{ color: "var(--good)" }} aria-hidden />
              ) : (
                <ShieldAlert size={20} style={{ color: "var(--critical)" }} aria-hidden />
              )}
              <div>
                <p className="text-[13px] font-semibold" style={{ color: chain.valid ? "var(--good)" : "var(--critical)" }}>
                  {chain.valid ? "Verified" : "Tampering detected"}
                </p>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink-3">
                  {chain.valid
                    ? `${int(chain.checked)} event${chain.checked === 1 ? "" : "s"} checked; every stored event still matches its hash.`
                    : `Event ${chain.broken_event_id}: ${chain.reason}`}
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Policy conditions">
            <ul className="grid gap-2.5">
              {policy_conditions.map((c) => (
                <li key={c.key} className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[12px] text-ink-2">{c.label}</p>
                    <p className="mt-0.5 text-[11px] text-ink-3">{c.detail}</p>
                  </div>
                  <ConditionBadge status={c.status} />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      <Panel title="History" subtitle={`${int(history.length)} events, oldest first.`} note={note}>
        <DataTable
          columns={historyCols}
          rows={history}
          rowKey={(e) => String(e.id)}
          maxHeight={420}
          compact
          empty="No history yet. Replacing a part, running a stress test or logging an incident all add an event."
        />
      </Panel>
    </div>
  );
}

/** One-line human summary of an event's details; the raw JSON is on hover. */
function EventDetails({ event }: { event: HistoryEvent }) {
  const d = event.details as Record<string, unknown>;
  let text: string;
  switch (event.type) {
    case "part_replaced":
      text = `${partLabel(String(d.part))} (was ${Number(d.life_used_pct_before).toFixed(1)}%)`;
      break;
    case "stress_test":
      text = `${d.n_races} races · ${String(d.weather).toLowerCase()} · ${d.parts_crossing_red} part(s) crossed red`;
      break;
    case "incident":
      text = String(d.description ?? "");
      break;
    case "driver_updated": {
      const after = d.after as { archetype?: string; overrides?: Record<string, number> } | undefined;
      const n = Object.keys(after?.overrides ?? {}).length;
      text = `${after?.archetype ?? "?"}${n ? ` + ${n} adjusted trait${n === 1 ? "" : "s"}` : ""}`;
      break;
    }
    default:
      text = Object.entries(d)
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
        .join(" · ");
  }
  return (
    <span className="block max-w-[520px] truncate" title={JSON.stringify(d, null, 2)}>
      {text}
    </span>
  );
}
