"""Apex Passport step 2: car/part records and a tamper-evident history chain.

Every ``history_events`` row's hash covers its own content (car, time, type,
details) plus the previous event's hash, exactly like a minimal blockchain.
Editing an old row's stored details without recomputing every hash after it
is what ``verify_chain`` detects -- it recomputes each hash from what is
actually stored and compares it to the hash that was stored alongside it.

This is deliberately not a cryptocurrency or a distributed ledger: it is a
single SQLite table with a hash column, doing the one thing a real passport
audit needs -- proving a record was not quietly edited after the fact.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum

from . import assumptions as A
from .car_profiles import CarProfile, car_profile_from_dict

GENESIS_HASH = "0" * 64  # the fixed prev_hash for a car's first history event


class HistoryEventType(str, Enum):
    RACE = "race"
    KERB_HIT = "kerb_hit"
    CONTACT = "contact"
    PART_REPLACED = "part_replaced"
    INSPECTION = "inspection"
    INCIDENT = "incident"
    STRESS_TEST = "stress_test"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_event_hash(car_id: str, time: str, event_type: str, details: dict,
                       prev_hash: str) -> str:
    payload = _canonical(dict(car_id=car_id, time=time, type=event_type,
                              details=details, prev_hash=prev_hash))
    return hashlib.sha256(payload.encode()).hexdigest()


# --------------------------------------------------------------------------
# Cars
# --------------------------------------------------------------------------
def create_car(store, name: str, car_class: str, car_profile: CarProfile) -> str:
    car_id = uuid.uuid4().hex[:12]
    store.exec(
        "INSERT INTO cars (id, name, class, car_profile_json, created_at) "
        "VALUES (?,?,?,?,?)",
        (car_id, name, car_class, _canonical(car_profile.to_dict()), _now()),
    )
    _init_parts(store, car_id)
    return car_id


def get_car(store, car_id: str) -> dict | None:
    row = store.q1("SELECT * FROM cars WHERE id=?", (car_id,))
    if not row:
        return None
    row["car_profile"] = json.loads(row.pop("car_profile_json"))
    return row


def list_cars(store) -> list[dict]:
    rows = store.q("SELECT * FROM cars ORDER BY created_at DESC")
    for r in rows:
        r["car_profile"] = json.loads(r.pop("car_profile_json"))
    return rows


def car_profile_of(store, car_id: str) -> CarProfile | None:
    car = get_car(store, car_id)
    return car_profile_from_dict(car["car_profile"]) if car else None


# --------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------
def part_status_for(life_used_pct: float) -> str:
    if life_used_pct >= A.PASSPORT_LIFE_RED_PCT:
        return "red"
    if life_used_pct >= A.PASSPORT_LIFE_AMBER_PCT:
        return "amber"
    return "green"


def _init_parts(store, car_id: str) -> None:
    now = _now()
    for name in A.PASSPORT_PARTS:
        store.exec(
            "INSERT OR IGNORE INTO parts (car_id, name, life_used_pct, part_cost, "
            "status, updated_at) VALUES (?,?,0,?, 'green', ?)",
            (car_id, name, A.PASSPORT_PART_COSTS.get(name, 0.0), now),
        )


def get_parts(store, car_id: str) -> list[dict]:
    return store.q(
        "SELECT * FROM parts WHERE car_id=? ORDER BY name", (car_id,))


def set_part_life(store, car_id: str, part_name: str, life_used_pct: float) -> None:
    life_used_pct = max(0.0, min(100.0, life_used_pct))
    store.exec(
        "UPDATE parts SET life_used_pct=?, status=?, updated_at=? "
        "WHERE car_id=? AND name=?",
        (life_used_pct, part_status_for(life_used_pct), _now(), car_id, part_name),
    )


def replace_part(store, car_id: str, part_name: str) -> dict:
    """Resets a part to 0% life used and logs a tamper-evident history event."""
    before = store.q1("SELECT * FROM parts WHERE car_id=? AND name=?",
                      (car_id, part_name))
    if not before:
        raise KeyError(f"car {car_id} has no part '{part_name}'")
    set_part_life(store, car_id, part_name, 0.0)
    event = record_event(store, car_id, HistoryEventType.PART_REPLACED, dict(
        part=part_name, life_used_pct_before=before["life_used_pct"],
    ))
    return event


# --------------------------------------------------------------------------
# Tamper-evident history
# --------------------------------------------------------------------------
def record_event(store, car_id: str, event_type: HistoryEventType | str,
                 details: dict, time: str | None = None) -> dict:
    event_type = event_type.value if isinstance(event_type, HistoryEventType) else event_type
    time = time or _now()
    last = store.q1(
        "SELECT hash, seq FROM history_events WHERE car_id=? "
        "ORDER BY seq DESC LIMIT 1", (car_id,))
    prev_hash = last["hash"] if last else GENESIS_HASH
    seq = (last["seq"] + 1) if last else 0
    h = compute_event_hash(car_id, time, event_type, details, prev_hash)
    cur = store.connect().execute(
        "INSERT INTO history_events (car_id, time, type, details_json, hash, "
        "prev_hash, seq) VALUES (?,?,?,?,?,?,?)",
        (car_id, time, event_type, _canonical(details), h, prev_hash, seq),
    )
    return dict(id=cur.lastrowid, car_id=car_id, time=time, type=event_type,
               details=details, hash=h, prev_hash=prev_hash, seq=seq)


def get_history(store, car_id: str) -> list[dict]:
    rows = store.q(
        "SELECT * FROM history_events WHERE car_id=? ORDER BY seq ASC", (car_id,))
    for r in rows:
        r["details"] = json.loads(r.pop("details_json"))
    return rows


def verify_chain(store, car_id: str) -> dict:
    """Recomputes every event's hash from its stored content and prev_hash,
    and checks it against the hash stored alongside it. A `valid=False`
    result names the first event whose stored content no longer matches its
    stored hash -- i.e. was edited after being written.
    """
    rows = store.q(
        "SELECT * FROM history_events WHERE car_id=? ORDER BY seq ASC", (car_id,))
    expected_prev = GENESIS_HASH
    for r in rows:
        details = json.loads(r["details_json"])
        recomputed = compute_event_hash(car_id, r["time"], r["type"], details,
                                        expected_prev)
        if r["prev_hash"] != expected_prev:
            return dict(valid=False, checked=r["seq"], broken_event_id=r["id"],
                       reason="prev_hash does not chain to the prior event")
        if recomputed != r["hash"]:
            return dict(valid=False, checked=r["seq"], broken_event_id=r["id"],
                       reason="stored content does not match its recorded hash "
                              "-- this event was altered after being written")
        expected_prev = r["hash"]
    return dict(valid=True, checked=len(rows), broken_event_id=None, reason=None)
