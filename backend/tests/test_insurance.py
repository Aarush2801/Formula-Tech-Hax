import os
import tempfile

import pytest

from apex import assumptions as A
from apex.car_profiles import from_preset
from apex.insurance import (
    build_claim_pack, evidence_pack, evidence_pack_html, insurer_risk_summary,
    list_incidents, log_incident, policy_conditions,
)
from apex.passport import HistoryEventType, create_car, record_event, set_part_life
from apex.storage import Store


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    s = Store(path)
    yield s
    s.connect().close()
    os.remove(path)


@pytest.fixture
def car_id(store):
    return create_car(store, "Insurance Test Car", "F4", from_preset("F4"))


def test_policy_conditions_all_met_for_fresh_car(store, car_id):
    conditions = policy_conditions(store, car_id)
    assert len(conditions) == 3
    assert all(c["status"] == "met" for c in conditions)


def test_parts_condition_breached_at_100_pct(store, car_id):
    set_part_life(store, car_id, "wheels", 100.0)
    conditions = policy_conditions(store, car_id)
    parts_cond = next(c for c in conditions if c["key"] == "parts_replaced_before_100_pct")
    assert parts_cond["status"] == "breached"


def test_parts_condition_at_risk_above_red_threshold(store, car_id):
    set_part_life(store, car_id, "wheels", A.PASSPORT_LIFE_RED_PCT + 1)
    conditions = policy_conditions(store, car_id)
    parts_cond = next(c for c in conditions if c["key"] == "parts_replaced_before_100_pct")
    assert parts_cond["status"] == "at_risk"


def test_safety_gear_condition_only_considers_harness_and_seat(store, car_id):
    set_part_life(store, car_id, "brakes", 100.0)  # not safety gear
    conditions = policy_conditions(store, car_id)
    gear_cond = next(c for c in conditions if c["key"] == "safety_gear_in_date")
    assert gear_cond["status"] == "met"

    set_part_life(store, car_id, "harness", 100.0)
    conditions = policy_conditions(store, car_id)
    gear_cond = next(c for c in conditions if c["key"] == "safety_gear_in_date")
    assert gear_cond["status"] == "breached"


def test_inspection_interval_transitions(store, car_id):
    interval = A.POLICY_INSPECTION_INTERVAL_RACES
    margin = A.POLICY_INSPECTION_WARNING_MARGIN
    for i in range(interval - margin):
        record_event(store, car_id, HistoryEventType.RACE, dict(n=i))
    conditions = policy_conditions(store, car_id)
    insp = next(c for c in conditions if c["key"] == "inspection_interval")
    assert insp["status"] in ("met", "at_risk")  # boundary-dependent, but never breached yet

    for i in range(margin):
        record_event(store, car_id, HistoryEventType.RACE, dict(n=100 + i))
    conditions = policy_conditions(store, car_id)
    insp = next(c for c in conditions if c["key"] == "inspection_interval")
    assert insp["status"] == "breached"

    record_event(store, car_id, HistoryEventType.INSPECTION, dict(note="done"))
    conditions = policy_conditions(store, car_id)
    insp = next(c for c in conditions if c["key"] == "inspection_interval")
    assert insp["status"] == "met"


def test_insurer_risk_summary_structure(store, car_id):
    summary = insurer_risk_summary(store, car_id)
    assert summary["car"]["id"] == car_id
    assert summary["chain_verification"]["valid"] is True
    assert summary["incident_count"] == 0
    assert "not an insurance quote" in summary["disclaimer"]
    assert isinstance(summary["plain_english_summary"], str) and len(summary["plain_english_summary"]) > 0


def test_log_incident_locks_before_snapshot(store, car_id):
    set_part_life(store, car_id, "brakes", 40.0)
    result = log_incident(store, car_id, "Contact at turn 4", affected_parts=["brakes"])
    assert result["incident_id"]
    before = {p["name"]: p for p in result["before_snapshot"]}
    assert before["brakes"]["life_used_pct"] == 40.0

    # Changing the part's life AFTER logging must not retroactively change the
    # locked "before" snapshot -- that is the entire point of locking it.
    set_part_life(store, car_id, "brakes", 95.0)
    incidents = list_incidents(store, car_id)
    assert incidents[0]["before_snapshot"]
    before_after_mutation = {p["name"]: p for p in incidents[0]["before_snapshot"]}
    assert before_after_mutation["brakes"]["life_used_pct"] == 40.0


def test_claim_pack_shows_before_after_difference(store, car_id):
    set_part_life(store, car_id, "brakes", 40.0)
    result = log_incident(store, car_id, "Heavy braking incident")
    set_part_life(store, car_id, "brakes", 95.0)  # damage discovered after the incident

    pack = build_claim_pack(store, car_id, result["incident_id"])
    brakes_row = next(c for c in pack["comparison"] if c["part"] == "brakes")
    assert brakes_row["life_used_pct_before"] == 40.0
    assert brakes_row["life_used_pct_after"] == 95.0
    assert brakes_row["changed"] is True
    assert pack["chain_verification"]["valid"] is True


def test_claim_pack_unknown_incident_raises(store, car_id):
    with pytest.raises(KeyError):
        build_claim_pack(store, car_id, "not-a-real-incident")


def test_evidence_pack_json_has_all_sections(store, car_id):
    log_incident(store, car_id, "Minor off-track excursion")
    pack = evidence_pack(store, car_id)
    for key in ("car", "parts", "history", "chain_verification", "incidents",
               "policy_conditions", "plain_english_summary", "disclaimer"):
        assert key in pack
    assert len(pack["incidents"]) == 1


def test_evidence_pack_html_renders_key_sections(store, car_id):
    log_incident(store, car_id, "Minor off-track excursion")
    doc = evidence_pack_html(store, car_id)
    assert "<html>" in doc
    assert "Insurance Test Car" in doc
    assert "not an insurance quote" in doc
    assert "VERIFIED" in doc  # chain is untampered


def test_evidence_pack_html_flags_broken_chain(store, car_id):
    import json as _json
    events = record_event(store, car_id, HistoryEventType.INSPECTION, dict(note="baseline"))
    store.exec("UPDATE history_events SET details_json=? WHERE id=?",
              (_json.dumps({"note": "tampered"}), events["id"]))
    doc = evidence_pack_html(store, car_id)
    assert "FAILED" in doc
