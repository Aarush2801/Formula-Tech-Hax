"use client";

import { ExternalLink, FileJson, Loader2, Lock, Plus, ShieldAlert, ShieldCheck } from "lucide-react";
import React from "react";

import { PageHeader } from "../../../components/Common";
import { ConditionBadge, PartStatusBadge, RequireCar } from "../../../components/passport";
import {
  Button,
  Column,
  DataTable,
  ErrorState,
  Panel,
  Skeleton,
  StatTile,
} from "../../../components/ui";
import { API_BASE } from "../../../lib/api";
import { datetime, dec, int } from "../../../lib/format";
import { Car, ClaimPack, Incident, partLabel, passportApi } from "../../../lib/passport";
import { useFetch } from "../../../lib/store";

export default function InsurancePage() {
  return (
    <>
      <PageHeader
        title="Insurance"
        lede="Evidence for an insurer, assembled from the car's recorded and simulated history: policy conditions, a verified history, and incident claim packs that lock the car's condition at the moment of reporting."
      />
      <RequireCar>{(car) => <Insurance key={car.id} car={car} />}</RequireCar>
    </>
  );
}

function Insurance({ car }: { car: Car }) {
  const summary = useFetch(() => passportApi.insurerSummary(car.id), [car.id]);
  const incidents = useFetch(() => passportApi.incidents(car.id), [car.id]);
  const [openIncident, setOpenIncident] = React.useState<string | null>(null);

  const reloadAll = () => {
    summary.reload();
    incidents.reload();
  };

  if (summary.error) return <ErrorState error={summary.error} onRetry={summary.reload} />;
  if (!summary.data) return <Skeleton h={320} />;
  const s = summary.data;
  const chain = s.chain_verification;
  const packUrl = `${API_BASE}/api/cars/${car.id}/evidence-pack`;

  const incidentCols: Column<Incident>[] = [
    { key: "occurred", header: "Occurred", render: (i) => <span className="num">{datetime(i.occurred_at)}</span> },
    { key: "desc", header: "Description", render: (i) => <span className="block max-w-[420px] truncate">{i.description}</span> },
    {
      key: "parts",
      header: "Affected parts",
      render: (i) => (i.affected_parts.length ? i.affected_parts.map(partLabel).join(", ") : "—"),
    },
  ];

  return (
    <div className="grid gap-3">
      <div
        className="rounded-md border px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink-2"
        style={{ borderColor: "var(--warning)44", background: "var(--warning)0d" }}
        role="note"
      >
        {s.disclaimer}
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="History chain"
          value={chain.valid ? "Verified" : "Failed"}
          tone={chain.valid ? "good" : "critical"}
          glyph={chain.valid ? "●" : "✕"}
          sub={`${int(chain.checked)} events checked`}
        />
        <StatTile label="History events" value={int(s.history_event_count)} />
        <StatTile label="Logged incidents" value={int(s.incident_count)} />
        <StatTile
          label="Latest stress test"
          value={s.latest_stress_test ? int(s.latest_stress_test.parts_crossing_red_count) : "—"}
          sub={s.latest_stress_test ? "parts crossed the replace threshold" : "none run yet"}
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
        <Panel
          title="Insurer summary"
          right={
            <span className="flex gap-2">
              <a href={`${packUrl}?format=html`} target="_blank" rel="noreferrer">
                <Button size="sm" variant="primary">
                  <ExternalLink size={11} /> Evidence pack
                </Button>
              </a>
              <a href={packUrl} target="_blank" rel="noreferrer">
                <Button size="sm">
                  <FileJson size={11} /> JSON
                </Button>
              </a>
            </span>
          }
          note={`Generated ${datetime(s.generated_at)}.`}
        >
          <p className="text-[12.5px] leading-relaxed text-ink-2">{s.plain_english_summary}</p>
        </Panel>

        <Panel title="Policy conditions" note="Illustrative conditions, not the wording of any real policy.">
          <ul className="grid gap-2.5">
            {s.policy_conditions.map((c) => (
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

      <div className="grid gap-3 xl:grid-cols-[2fr_3fr]">
        <IncidentForm car={car} onLogged={(id) => { reloadAll(); setOpenIncident(id); }} />
        <Panel title="Incidents" subtitle="Select one to open its claim pack.">
          {incidents.error ? <ErrorState error={incidents.error} /> : null}
          <DataTable
            columns={incidentCols}
            rows={incidents.data?.incidents ?? []}
            rowKey={(i) => i.id}
            selectedKey={openIncident ?? undefined}
            onRowClick={(i) => setOpenIncident(i.id)}
            compact
            empty="No incidents logged."
          />
        </Panel>
      </div>

      {openIncident && <ClaimPackView carId={car.id} incidentId={openIncident} />}
    </div>
  );
}

/* ------------------------------------------------------ incident form --- */

function IncidentForm({ car, onLogged }: { car: Car; onLogged: (id: string) => void }) {
  const parts = useFetch(() => passportApi.passport(car.id), [car.id]);
  const [description, setDescription] = React.useState("");
  const [occurredAt, setOccurredAt] = React.useState("");
  const [affected, setAffected] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<unknown>(null);

  const toggle = (name: string) =>
    setAffected((a) => (a.includes(name) ? a.filter((x) => x !== name) : [...a, name]));

  const submit = async () => {
    if (!description.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await passportApi.logIncident(car.id, {
        description: description.trim(),
        occurred_at: occurredAt ? new Date(occurredAt).toISOString() : undefined,
        affected_parts: affected,
      });
      setDescription("");
      setOccurredAt("");
      setAffected([]);
      onLogged(res.incident_id);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Log an incident"
      subtitle="Logging locks in the car's part condition right now as the 'before' state, so old wear and new damage can't be confused later."
    >
      {err ? <ErrorState error={err} /> : null}
      <div className="grid gap-3">
        <label className="flex flex-col gap-1">
          <span className="label-xs">What happened</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="e.g. Contact with car #12 at Turn 6, left-front impact"
            className="rounded border border-line-strong bg-surface-2 px-2 py-1.5 text-[12px] text-ink outline-none focus:border-[color:var(--accent)]"
          />
        </label>
        <label className="flex w-[240px] flex-col gap-1">
          <span className="label-xs">When (optional — defaults to now)</span>
          <input
            type="datetime-local"
            value={occurredAt}
            onChange={(e) => setOccurredAt(e.target.value)}
            className="rounded border border-line-strong bg-surface-2 px-2 py-1.5 text-[12px] text-ink outline-none focus:border-[color:var(--accent)]"
          />
        </label>
        <fieldset>
          <legend className="label-xs mb-1.5">Affected parts</legend>
          <div className="flex flex-wrap gap-1.5">
            {(parts.data?.parts ?? []).map((p) => {
              const on = affected.includes(p.name);
              return (
                <button
                  key={p.name}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(p.name)}
                  className={`rounded border px-2 py-1 text-[11px] transition-colors ${
                    on
                      ? "border-[color:var(--accent)] bg-surface-3 text-ink"
                      : "border-line-strong text-ink-3 hover:text-ink-2"
                  }`}
                >
                  {partLabel(p.name)}
                </button>
              );
            })}
          </div>
        </fieldset>
        <div>
          <Button variant="primary" onClick={submit} disabled={busy || !description.trim()}>
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
            Log incident
          </Button>
        </div>
      </div>
    </Panel>
  );
}

/* --------------------------------------------------------- claim pack --- */

function ClaimPackView({ carId, incidentId }: { carId: string; incidentId: string }) {
  const pack = useFetch(() => passportApi.claimPack(carId, incidentId), [carId, incidentId]);
  if (pack.error) return <ErrorState error={pack.error} onRetry={pack.reload} />;
  if (!pack.data) return <Skeleton h={220} />;
  const p = pack.data;
  const chain = p.chain_verification;

  const cols: Column<ClaimPack["comparison"][number]>[] = [
    {
      key: "part",
      header: "Part",
      render: (r) => (
        <span className={p.incident.affected_parts.includes(r.part) ? "font-semibold text-ink" : ""}>
          {partLabel(r.part)}
          {p.incident.affected_parts.includes(r.part) && <span className="ml-1.5 text-[10px] text-ink-3">reported</span>}
        </span>
      ),
    },
    { key: "before", header: "Before (locked)", align: "right", render: (r) => (r.life_used_pct_before === null ? "—" : `${dec(r.life_used_pct_before, 1)}%`) },
    { key: "sb", header: "", render: (r) => (r.status_before ? <PartStatusBadge status={r.status_before} /> : null) },
    { key: "after", header: "Now", align: "right", render: (r) => `${dec(r.life_used_pct_after, 1)}%` },
    { key: "sa", header: "", render: (r) => <PartStatusBadge status={r.status_after} /> },
    { key: "changed", header: "Changed", render: (r) => (r.changed ? "Yes" : "—") },
  ];

  return (
    <Panel
      title="Claim pack"
      subtitle={p.incident.description}
      right={
        <span className="flex items-center gap-1.5 text-[11px]" style={{ color: chain.valid ? "var(--good)" : "var(--critical)" }}>
          {chain.valid ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
          {chain.valid ? "History verified" : "History failed verification"}
        </span>
      }
      note={p.disclaimer}
    >
      <p className="mb-2 flex items-center gap-1.5 text-[11px] text-ink-3">
        <Lock size={11} aria-hidden /> Condition locked when reported, {datetime(p.incident.reported_at)}. Occurred{" "}
        {datetime(p.incident.occurred_at)}.
      </p>
      <DataTable columns={cols} rows={p.comparison} rowKey={(r) => r.part} compact />
    </Panel>
  );
}
