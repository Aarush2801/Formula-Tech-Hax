"""Apex Passport step 2: cars/parts/history and the tamper-evident hash chain."""
import os
import tempfile

import pytest

from apex import assumptions as A
from apex.car_profiles import from_preset
from apex.passport import (
    GENESIS_HASH, HistoryEventType, create_car, get_history, get_parts,
    part_status_for, record_event, replace_part, verify_chain,
)
from apex.storage import Store


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # Store creates it fresh
    s = Store(path)
    yield s
    s.connect().close()
    os.remove(path)


@pytest.fixture
def car_id(store):
    return create_car(store, "Test Car #1", "F3", from_preset("F3"))


def test_create_car_initialises_all_parts(store, car_id):
    parts = get_parts(store, car_id)
    names = {p["name"] for p in parts}
    assert names == set(A.PASSPORT_PARTS)
    assert all(p["life_used_pct"] == 0 for p in parts)
    assert all(p["status"] == "green" for p in parts)
    assert all(p["part_cost"] > 0 for p in parts)


def test_part_status_thresholds():
    assert part_status_for(0.0) == "green"
    assert part_status_for(A.PASSPORT_LIFE_AMBER_PCT - 1) == "green"
    assert part_status_for(A.PASSPORT_LIFE_AMBER_PCT) == "amber"
    assert part_status_for(A.PASSPORT_LIFE_RED_PCT - 1) == "amber"
    assert part_status_for(A.PASSPORT_LIFE_RED_PCT) == "red"
    assert part_status_for(100.0) == "red"


def test_replace_part_resets_life_and_logs_event(store, car_id):
    from apex.passport import set_part_life
    set_part_life(store, car_id, "brakes", 82.0)
    event = replace_part(store, car_id, "brakes")

    parts = {p["name"]: p for p in get_parts(store, car_id)}
    assert parts["brakes"]["life_used_pct"] == 0.0
    assert parts["brakes"]["status"] == "green"

    assert event["type"] == HistoryEventType.PART_REPLACED.value
    assert event["details"]["part"] == "brakes"
    assert event["details"]["life_used_pct_before"] == 82.0

    history = get_history(store, car_id)
    assert history[-1]["id"] == event["id"]


def test_first_event_chains_to_genesis(store, car_id):
    event = record_event(store, car_id, HistoryEventType.INSPECTION, dict(note="baseline"))
    assert event["prev_hash"] == GENESIS_HASH
    assert event["seq"] == 0


def test_hash_chain_links_sequential_events(store, car_id):
    e1 = record_event(store, car_id, HistoryEventType.RACE, dict(track="vale_park"))
    e2 = record_event(store, car_id, HistoryEventType.KERB_HIT, dict(severity=0.4))
    e3 = record_event(store, car_id, HistoryEventType.CONTACT, dict(impact_speed=6.2))
    assert e1["prev_hash"] == GENESIS_HASH
    assert e2["prev_hash"] == e1["hash"]
    assert e3["prev_hash"] == e2["hash"]
    assert len({e1["hash"], e2["hash"], e3["hash"]}) == 3  # all distinct


def test_verify_chain_valid_for_untouched_history(store, car_id):
    for i in range(5):
        record_event(store, car_id, HistoryEventType.RACE, dict(race_number=i))
    result = verify_chain(store, car_id)
    assert result["valid"] is True
    assert result["checked"] == 5
    assert result["broken_event_id"] is None


def test_verify_chain_valid_for_empty_history(store, car_id):
    result = verify_chain(store, car_id)
    assert result["valid"] is True
    assert result["checked"] == 0


def test_verify_chain_detects_edited_event_details(store, car_id):
    """The exact scenario the spec asks for: editing an old event is detected."""
    e1 = record_event(store, car_id, HistoryEventType.RACE, dict(position=8))
    record_event(store, car_id, HistoryEventType.RACE, dict(position=3))
    record_event(store, car_id, HistoryEventType.INSPECTION, dict(note="ok"))

    assert verify_chain(store, car_id)["valid"] is True

    # Tamper with the first event's details directly in the database, bypassing
    # record_event -- e.g. someone editing the row by hand to hide a bad result.
    import json
    store.exec("UPDATE history_events SET details_json=? WHERE id=?",
              (json.dumps({"position": 1}), e1["id"]))

    result = verify_chain(store, car_id)
    assert result["valid"] is False
    assert result["broken_event_id"] == e1["id"]


def test_verify_chain_detects_directly_forged_hash(store, car_id):
    """Editing both details AND the hash to match must still be caught,
    because it breaks the prev_hash link to the next event."""
    e1 = record_event(store, car_id, HistoryEventType.RACE, dict(position=8))
    e2 = record_event(store, car_id, HistoryEventType.RACE, dict(position=3))

    import json
    from apex.passport import compute_event_hash
    forged_details = {"position": 1}
    forged_hash = compute_event_hash(car_id, e1["time"], e1["type"], forged_details,
                                     e1["prev_hash"])
    store.exec("UPDATE history_events SET details_json=?, hash=? WHERE id=?",
              (json.dumps(forged_details), forged_hash, e1["id"]))

    # e1 now looks internally consistent, but e2's prev_hash no longer matches
    # e1's new (forged) hash, so the chain is still broken from e2 onward.
    result = verify_chain(store, car_id)
    assert result["valid"] is False
    assert result["broken_event_id"] == e2["id"]


def test_get_history_is_chronological(store, car_id):
    for i in range(4):
        record_event(store, car_id, HistoryEventType.RACE, dict(n=i))
    history = get_history(store, car_id)
    assert [h["details"]["n"] for h in history] == [0, 1, 2, 3]
