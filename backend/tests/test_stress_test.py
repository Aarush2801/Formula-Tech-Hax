import os
import tempfile

import pytest

from apex import assumptions as A
from apex.car_profiles import from_preset
from apex.passport import create_car, get_history, set_part_life
from apex.storage import Store
from apex.stress_test import run_stress_test

N_RACES_FAST = 10  # small for test speed; determinism doesn't depend on N


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
    return create_car(store, "Stress Test Car", "F3", from_preset("F3"))


def test_unknown_car_raises(store):
    with pytest.raises(KeyError):
        run_stress_test(store, "no-such-car", n_races=N_RACES_FAST)


def test_run_stress_test_produces_full_report(store, car_id):
    result = run_stress_test(store, car_id, track_id="vale_park", weather="WET",
                             n_races=N_RACES_FAST, base_seed=42)
    assert result["car_id"] == car_id
    assert result["n_races"] == N_RACES_FAST
    assert len(result["parts"]) == len(A.PASSPORT_PARTS)
    for p in result["parts"]:
        assert p["races_evaluated"] == N_RACES_FAST
        assert p["status"] in ("green", "amber", "red")
        assert p["predicted_min_pct"] <= p["predicted_median_pct"] <= p["predicted_max_pct"]
    assert "total" in result["cost_forecast"]
    assert len(result["recommendations"]) >= 1
    assert "not a real-world probability" in result["note"] or "N of M simulated races" in result["note"]


def test_run_stress_test_is_deterministic(store, car_id):
    r1 = run_stress_test(store, car_id, track_id="vale_park", weather="DRY",
                         n_races=N_RACES_FAST, base_seed=777)
    r2 = run_stress_test(store, car_id, track_id="vale_park", weather="DRY",
                         n_races=N_RACES_FAST, base_seed=777)
    p1 = {p["part"]: p["predicted_median_pct"] for p in r1["parts"]}
    p2 = {p["part"]: p["predicted_median_pct"] for p in r2["parts"]}
    assert p1 == p2
    assert r1["parts_crossing_red_count"] == r2["parts_crossing_red_count"]
    assert r1["cost_forecast"] == r2["cost_forecast"]
    assert r1["n_close_calls"] == r2["n_close_calls"]


def test_different_seed_can_differ(store, car_id):
    r1 = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=1)
    r2 = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=999_999)
    # Not asserting inequality (small N could coincidentally match) -- just that
    # both produce valid, independently-computed reports.
    assert r1["batch_id"] != r2["batch_id"]


def test_worn_part_raises_predicted_life_used(store, car_id):
    set_part_life(store, car_id, "brakes", 60.0)
    result = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=55)
    brakes = next(p for p in result["parts"] if p["part"] == "brakes")
    assert brakes["current_life_used_pct"] == 60.0
    assert brakes["predicted_median_pct"] >= 60.0


def test_stress_test_logs_history_event(store, car_id):
    before = len(get_history(store, car_id))
    result = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=5)
    after = get_history(store, car_id)
    assert len(after) == before + 1
    assert after[-1]["type"] == "stress_test"
    assert after[-1]["details"]["batch_id"] == result["batch_id"]


def test_recommendation_language_for_red_part(store, car_id):
    set_part_life(store, car_id, "suspension_fl", 99.0)
    result = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=3)
    fl = next(p for p in result["parts"] if p["part"] == "suspension_fl")
    assert fl["status"] == "red"
    joined = " ".join(result["recommendations"])
    assert "suspension fl" in joined.lower()
    assert "replace" in joined.lower()


def test_close_calls_reflect_replays_generated_after_the_batch(store, car_id):
    result = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=42)
    replayed = {r["id"] for r in store.q(
        "SELECT id FROM runs WHERE batch_id=? AND has_replay=1", (result["batch_id"],))}
    for call in result["close_calls"]:
        assert call["has_replay"] == (call["run_id"] in replayed)


def test_predicted_wear_is_never_below_current_condition(store, car_id):
    set_part_life(store, car_id, "wheels", 40.0)
    result = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=42)
    for p in result["parts"]:
        assert p["predicted_min_pct"] >= p["current_life_used_pct"]
