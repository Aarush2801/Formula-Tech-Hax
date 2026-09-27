"""Apex Passport demo seed: every screen has something to show."""
import os
import tempfile

import pytest

from apex import assumptions as A
from apex.insurance import build_claim_pack, policy_conditions
from apex.passport import get_history, get_parts, list_cars, verify_chain
from apex.passport_demo import DEMO_CAR_NAME, seed_passport_demo
from apex.storage import Store
from apex.stress_test import latest_stress_test

N_RACES_FAST = 10


@pytest.fixture(scope="module")
def seeded():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    store = Store(path)
    out = seed_passport_demo(store, n_races=N_RACES_FAST, log=lambda _: None)
    yield store, out
    store.connect().close()
    os.remove(path)


def test_creates_two_cars(seeded):
    store, out = seeded
    assert out["created"]
    assert {c["id"] for c in list_cars(store)} == {out["car_id"], out["student_car_id"]}


def test_history_is_chained_and_in_time_order(seeded):
    store, out = seeded
    history = get_history(store, out["car_id"])
    assert verify_chain(store, out["car_id"])["valid"]
    times = [e["time"] for e in history]
    assert times == sorted(times)
    types = [e["type"] for e in history]
    assert types[0] == "inspection"
    assert types.count("race") == 4
    assert "part_replaced" in types and "incident" in types and "stress_test" in types


def test_race_events_are_labelled_as_simulated(seeded):
    store, out = seeded
    races = [e for e in get_history(store, out["car_id"]) if e["type"] == "race"]
    assert all(e["details"]["source"] == "simulated for demo" for e in races)


def test_part_condition_spans_statuses(seeded):
    store, out = seeded
    statuses = {p["name"]: p["status"] for p in get_parts(store, out["car_id"])}
    assert statuses["wheels"] == "red"
    assert statuses["suspension_fl"] == "green"  # replaced mid-history
    assert "amber" in statuses.values()


def test_policy_conditions_show_risk(seeded):
    store, out = seeded
    by_key = {c["key"]: c["status"] for c in policy_conditions(store, out["car_id"])}
    assert by_key["parts_replaced_before_100_pct"] == "at_risk"
    # Four races since the intake inspection: inside the warning margin.
    assert A.POLICY_INSPECTION_INTERVAL_RACES - A.POLICY_INSPECTION_WARNING_MARGIN <= 4
    assert by_key["inspection_interval"] == "at_risk"


def test_claim_pack_shows_new_damage(seeded):
    store, out = seeded
    pack = build_claim_pack(store, out["car_id"], out["incident_id"])
    fr = next(r for r in pack["comparison"] if r["part"] == "suspension_fr")
    assert fr["changed"]
    assert fr["life_used_pct_after"] >= fr["life_used_pct_before"] + 30.0


def test_stress_test_present(seeded):
    store, out = seeded
    result = latest_stress_test(store, out["car_id"])
    assert result["n_races"] == N_RACES_FAST


def test_second_run_is_a_no_op(seeded):
    store, out = seeded
    again = seed_passport_demo(store, n_races=N_RACES_FAST, log=lambda _: None)
    assert not again["created"] and again["car_id"] == out["car_id"]
    assert sum(1 for c in list_cars(store) if c["name"] == DEMO_CAR_NAME) == 1
