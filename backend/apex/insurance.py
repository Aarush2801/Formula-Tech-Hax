"""Apex Passport step 4: insurance-facing outputs.

Everything here is *supporting evidence assembled from this car's simulated
and recorded history* -- never an insurance quote, a claim decision, or a
statement of real-world risk. That framing is repeated in every payload this
module returns, not left to the caller to remember.
"""
from __future__ import annotations

import html
import json
import uuid
from datetime import datetime, timezone

from . import assumptions as A
from .passport import (
    GENESIS_HASH, HistoryEventType, get_car, get_history, get_parts,
    part_status_for, record_event, verify_chain,
)
from .stress_test import latest_stress_test

EVIDENCE_DISCLAIMER = (
    "This document is supporting evidence assembled from this car's simulated "
    "and recorded history. It is not an insurance quote, a claim decision, or "
    "a statement of real-world crash probability."
)


# --------------------------------------------------------------------------
# Policy conditions
# --------------------------------------------------------------------------
def _races_since_last_inspection(history: list[dict]) -> int:
    count = 0
    for event in reversed(history):
        if event["type"] == HistoryEventType.INSPECTION.value:
            break
        if event["type"] == HistoryEventType.RACE.value:
            count += 1
    return count


def policy_conditions(store, car_id: str) -> list[dict]:
    """Three illustrative policy conditions, each met / at_risk / breached.
    Not the wording or terms of any real insurance policy."""
    parts = get_parts(store, car_id)
    history = get_history(store, car_id)
    conditions = []

    worst_part = max(parts, key=lambda p: p["life_used_pct"]) if parts else None
    if worst_part is None:
        cond_status, detail = "met", "No parts on record."
    elif worst_part["life_used_pct"] >= 100.0:
        cond_status = "breached"
        detail = f"{worst_part['name'].replace('_', ' ')} is at or beyond 100% life used."
    elif worst_part["life_used_pct"] >= A.PASSPORT_LIFE_RED_PCT:
        cond_status = "at_risk"
        detail = (f"{worst_part['name'].replace('_', ' ')} is at "
                 f"{worst_part['life_used_pct']:.1f}% life used.")
    else:
        cond_status, detail = "met", "All parts are below the replacement threshold."
    conditions.append(dict(
        key="parts_replaced_before_100_pct", label="Parts replaced before 100% life",
        status=cond_status, detail=detail,
    ))

    gear = [p for p in parts if p["name"] in ("harness", "seat")]
    worst_gear = max(gear, key=lambda p: p["life_used_pct"]) if gear else None
    if worst_gear is None:
        gear_status, gear_detail = "met", "No safety gear on record."
    elif worst_gear["life_used_pct"] >= 100.0:
        gear_status = "breached"
        gear_detail = f"{worst_gear['name']} is at or beyond its tracked service life."
    elif worst_gear["life_used_pct"] >= A.PASSPORT_LIFE_RED_PCT:
        gear_status = "at_risk"
        gear_detail = f"{worst_gear['name']} is at {worst_gear['life_used_pct']:.1f}% of tracked service life."
    else:
        gear_status, gear_detail = "met", "Harness and seat are within their tracked service life."
    conditions.append(dict(
        key="safety_gear_in_date", label="Safety gear in date",
        status=gear_status, detail=gear_detail,
    ))

    since = _races_since_last_inspection(history)
    interval = A.POLICY_INSPECTION_INTERVAL_RACES
    margin = A.POLICY_INSPECTION_WARNING_MARGIN
    if since >= interval:
        insp_status = "breached"
    elif since >= interval - margin:
        insp_status = "at_risk"
    else:
        insp_status = "met"
    conditions.append(dict(
        key="inspection_interval", label=f"Inspection every {interval} races",
        status=insp_status,
        detail=f"{since} race(s) recorded since the last inspection.",
    ))

    return conditions


# --------------------------------------------------------------------------
# Insurer risk summary
# --------------------------------------------------------------------------
def insurer_risk_summary(store, car_id: str) -> dict:
    car = get_car(store, car_id)
    if not car:
        raise KeyError(f"unknown car '{car_id}'")
    parts = get_parts(store, car_id)
    history = get_history(store, car_id)
    chain = verify_chain(store, car_id)
    conditions = policy_conditions(store, car_id)
    incidents = [e for e in history if e["type"] == HistoryEventType.INCIDENT.value]
    contacts = [e for e in history if e["type"] == HistoryEventType.CONTACT.value]
    latest_test = latest_stress_test(store, car_id)

    breached = [c for c in conditions if c["status"] == "breached"]
    at_risk = [c for c in conditions if c["status"] == "at_risk"]
    red_parts = [p for p in parts if p["status"] == "red"]

    summary_lines = [
        f"{car['name']} ({car['class']}) has {len(history)} recorded history "
        f"event(s) and {len(incidents)} logged real-world incident(s).",
        f"History chain verification: {'PASSED' if chain['valid'] else 'FAILED'} "
        f"({chain['checked']} event(s) checked).",
    ]
    if red_parts:
        summary_lines.append(
            "Parts currently at or above the replacement threshold: "
            + ", ".join(p["name"].replace("_", " ") for p in red_parts) + ".")
    else:
        summary_lines.append("No part is currently at or above the replacement threshold.")
    if breached:
        summary_lines.append(
            "Policy conditions currently breached: "
            + ", ".join(c["label"] for c in breached) + ".")
    elif at_risk:
        summary_lines.append(
            "Policy conditions at risk: " + ", ".join(c["label"] for c in at_risk) + ".")
    else:
        summary_lines.append("All tracked policy conditions are currently met.")
    if latest_test:
        summary_lines.append(
            f"Latest stress test ({latest_test['n_races']} simulated races at "
            f"{latest_test['weather']}): {latest_test['parts_crossing_red_count']} "
            "part(s) crossed the replacement threshold in at least one simulated race.")

    return dict(
        car=car, parts=parts, policy_conditions=conditions,
        chain_verification=chain,
        incident_count=len(incidents), contact_event_count=len(contacts),
        history_event_count=len(history),
        latest_stress_test=latest_test,
        plain_english_summary=" ".join(summary_lines),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        disclaimer=EVIDENCE_DISCLAIMER,
    )


# --------------------------------------------------------------------------
# Incident / claim pack flow
# --------------------------------------------------------------------------
def log_incident(store, car_id: str, description: str, occurred_at: str | None = None,
                 affected_parts: list[str] | None = None) -> dict:
    """Locks in the car's condition *right now* as the 'before' state, then
    records the incident. The claim pack later compares this locked snapshot
    against current condition, so there is no dispute about old vs new damage.
    """
    car = get_car(store, car_id)
    if not car:
        raise KeyError(f"unknown car '{car_id}'")
    before_snapshot = get_parts(store, car_id)
    occurred_at = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    incident_id = uuid.uuid4().hex[:12]

    event = record_event(store, car_id, HistoryEventType.INCIDENT, dict(
        incident_id=incident_id, description=description, occurred_at=occurred_at,
        affected_parts=affected_parts or [],
    ))

    store.exec(
        "INSERT INTO incidents (id, car_id, reported_at, occurred_at, description, "
        "affected_parts_json, before_snapshot_json, history_event_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (incident_id, car_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         occurred_at, description, json.dumps(affected_parts or []),
         json.dumps(before_snapshot), event["id"]),
    )
    return dict(incident_id=incident_id, history_event_id=event["id"],
               before_snapshot=before_snapshot)


def get_incident(store, car_id: str, incident_id: str) -> dict | None:
    row = store.q1("SELECT * FROM incidents WHERE id=? AND car_id=?",
                   (incident_id, car_id))
    if not row:
        return None
    row["affected_parts"] = json.loads(row.pop("affected_parts_json"))
    row["before_snapshot"] = json.loads(row.pop("before_snapshot_json"))
    return row


def list_incidents(store, car_id: str) -> list[dict]:
    rows = store.q("SELECT * FROM incidents WHERE car_id=? ORDER BY occurred_at DESC",
                   (car_id,))
    for r in rows:
        r["affected_parts"] = json.loads(r.pop("affected_parts_json"))
        r["before_snapshot"] = json.loads(r.pop("before_snapshot_json"))
    return rows


def build_claim_pack(store, car_id: str, incident_id: str) -> dict:
    car = get_car(store, car_id)
    incident = get_incident(store, car_id, incident_id)
    if not car or not incident:
        raise KeyError(f"unknown car/incident '{car_id}'/'{incident_id}'")

    after = get_parts(store, car_id)
    before_by_name = {p["name"]: p for p in incident["before_snapshot"]}
    comparison = []
    for p in after:
        b = before_by_name.get(p["name"], {})
        comparison.append(dict(
            part=p["name"],
            life_used_pct_before=b.get("life_used_pct"),
            life_used_pct_after=p["life_used_pct"],
            status_before=b.get("status"),
            status_after=p["status"],
            changed=b.get("life_used_pct") != p["life_used_pct"],
        ))

    return dict(
        car=car, incident=incident, comparison=comparison,
        chain_verification=verify_chain(store, car_id),
        disclaimer=EVIDENCE_DISCLAIMER,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------------
# Evidence pack (JSON + printable HTML)
# --------------------------------------------------------------------------
def evidence_pack(store, car_id: str) -> dict:
    car = get_car(store, car_id)
    if not car:
        raise KeyError(f"unknown car '{car_id}'")
    return dict(
        car=car,
        parts=get_parts(store, car_id),
        history=get_history(store, car_id),
        chain_verification=verify_chain(store, car_id),
        incidents=list_incidents(store, car_id),
        latest_stress_test=latest_stress_test(store, car_id),
        policy_conditions=policy_conditions(store, car_id),
        plain_english_summary=insurer_risk_summary(store, car_id)["plain_english_summary"],
        disclaimer=EVIDENCE_DISCLAIMER,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _esc(x) -> str:
    return html.escape(str(x))


def evidence_pack_html(store, car_id: str) -> str:
    pack = evidence_pack(store, car_id)
    car = pack["car"]
    chain = pack["chain_verification"]

    rows_parts = "".join(
        f"<tr><td>{_esc(p['name'].replace('_', ' '))}</td>"
        f"<td>{p['life_used_pct']:.1f}%</td>"
        f"<td class='status-{p['status']}'>{_esc(p['status'].upper())}</td></tr>"
        for p in pack["parts"]
    )
    rows_history = "".join(
        f"<tr><td>{_esc(e['time'])}</td><td>{_esc(e['type'])}</td>"
        f"<td>{_esc(json.dumps(e['details']))}</td>"
        f"<td class='mono'>{_esc(e['hash'][:12])}...</td></tr>"
        for e in pack["history"]
    )
    rows_conditions = "".join(
        f"<tr><td>{_esc(c['label'])}</td>"
        f"<td class='status-{c['status']}'>{_esc(c['status'].replace('_', ' ').upper())}</td>"
        f"<td>{_esc(c['detail'])}</td></tr>"
        for c in pack["policy_conditions"]
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Apex Passport — {_esc(car['name'])}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; color: #1a1a1a; }}
h1 {{ margin-bottom: 0; }} .sub {{ color: #666; margin-top: 0.25rem; }}
table {{ width: 100%; border-collapse: collapse; margin: 1rem 0 2rem; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9rem; }}
th {{ background: #f2f2f2; }}
.status-green {{ color: #1a7f37; font-weight: 600; }}
.status-amber, .status-at_risk {{ color: #9a6700; font-weight: 600; }}
.status-red, .status-breached {{ color: #b91c1c; font-weight: 600; }}
.mono {{ font-family: monospace; font-size: 0.85rem; }}
.banner {{ background: #fff8e6; border: 1px solid #f0d78c; padding: 0.75rem 1rem; border-radius: 4px; margin: 1rem 0; }}
.chain-ok {{ color: #1a7f37; }} .chain-fail {{ color: #b91c1c; }}
</style></head>
<body>
<h1>Apex Passport</h1>
<p class="sub">{_esc(car['name'])} — class {_esc(car['class'])} — id {_esc(car['id'])}</p>
<div class="banner">{_esc(pack['disclaimer'])}</div>

<h2>Summary</h2>
<p>{_esc(pack['plain_english_summary'])}</p>

<h2>History chain verification</h2>
<p class="{'chain-ok' if chain['valid'] else 'chain-fail'}">
  {'VERIFIED — ' + str(chain['checked']) + ' event(s) checked, no tampering detected.'
    if chain['valid'] else 'FAILED at event ' + str(chain['broken_event_id']) + ': ' + _esc(chain['reason'])}
</p>

<h2>Policy conditions</h2>
<table><tr><th>Condition</th><th>Status</th><th>Detail</th></tr>{rows_conditions}</table>

<h2>Part health</h2>
<table><tr><th>Part</th><th>Life used</th><th>Status</th></tr>{rows_parts}</table>

<h2>History ({len(pack['history'])} events)</h2>
<table><tr><th>Time</th><th>Type</th><th>Details</th><th>Hash</th></tr>{rows_history}</table>

<p class="sub">Generated {_esc(pack['generated_at'])}. {_esc(pack['disclaimer'])}</p>
</body></html>"""
