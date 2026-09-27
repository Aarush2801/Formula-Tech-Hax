"""Apex Passport: the team driver a car carries into its stress tests."""
import os
import sqlite3
import tempfile

import pytest

from apex.car_profiles import from_preset
from apex.drivers import ARCHETYPES, TEAM_DRIVER_TRAITS, apply_team_driver, build_roster
from apex.passport import (
    DEFAULT_DRIVER_ARCHETYPE, create_car, get_car, get_history, set_team_driver,
    verify_chain,
)
from apex.storage import Store
from apex.stress_test import run_stress_test

N_RACES_FAST = 10


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    s = Store(path)
    yield s
    s.connect().close()
    os.remove(path)


def test_overrides_replace_only_named_traits():
    roster = apply_team_driver(build_roster(22), "SMOOTH",
                               dict(aggression=0.9, reaction_time=0.3))
    team, base = roster[0], ARCHETYPES["SMOOTH"]
    assert team.aggression == 0.9 and team.reaction_time == 0.3
    assert team.risk_tolerance == base["risk_tolerance"]
    assert team.provenance == "team_custom"


def test_overrides_are_clamped_and_unknown_keys_dropped():
    team = apply_team_driver(build_roster(22), "SMOOTH",
                             dict(aggression=5.0, reaction_time=0.0, not_a_trait=1.0))[0]
    assert team.aggression == TEAM_DRIVER_TRAITS["aggression"]["max"]
    assert team.reaction_time == TEAM_DRIVER_TRAITS["reaction_time"]["min"]
    assert not hasattr(team, "not_a_trait")


def test_no_overrides_is_the_plain_archetype():
    plain = apply_team_driver(build_roster(22), "LATE_BRAKER")[0]
    empty = apply_team_driver(build_roster(22), "LATE_BRAKER", {})[0]
    assert plain == empty
    assert plain.provenance == "generic_archetype"


def test_new_car_gets_default_driver(store):
    car = get_car(store, create_car(store, "Car", "F3", from_preset("F3")))
    assert car["team_driver"] == dict(archetype=DEFAULT_DRIVER_ARCHETYPE, overrides={})


def test_set_team_driver_persists_and_logs_chained_event(store):
    car_id = create_car(store, "Car", "F3", from_preset("F3"))
    car = set_team_driver(store, car_id, dict(archetype="HIGH_RISK",
                                              overrides=dict(aggression=0.4)))
    assert car["team_driver"] == dict(archetype="HIGH_RISK", overrides=dict(aggression=0.4))
    last = get_history(store, car_id)[-1]
    assert last["type"] == "driver_updated"
    assert last["details"]["after"]["archetype"] == "HIGH_RISK"
    assert verify_chain(store, car_id)["valid"]


def test_unknown_archetype_rejected(store):
    car_id = create_car(store, "Car", "F3", from_preset("F3"))
    with pytest.raises(ValueError):
        set_team_driver(store, car_id, dict(archetype="NOT_REAL"))


def test_database_without_driver_column_is_migrated(store):
    """A cars table written before team drivers existed gains the column in
    place, and its cars read back with the default driver."""
    path = store.path
    store.connect().close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE cars")
    conn.execute("CREATE TABLE cars (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                 "class TEXT NOT NULL, car_profile_json TEXT NOT NULL, "
                 "created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO cars VALUES ('old', 'Old', 'F3', '{}', '2026-01-01')")
    conn.commit()
    conn.close()
    migrated = Store(path)
    assert get_car(migrated, "old")["team_driver"]["archetype"] == DEFAULT_DRIVER_ARCHETYPE


def test_stress_test_uses_saved_driver(store):
    car_id = create_car(store, "Car", "F3", from_preset("F3"))
    baseline = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=7)
    set_team_driver(store, car_id, dict(archetype="HIGH_RISK",
                                        overrides=dict(error_probability=2.5)))
    custom = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=7)
    assert baseline["driver"]["archetype"] == DEFAULT_DRIVER_ARCHETYPE
    assert custom["driver"] == dict(archetype="HIGH_RISK",
                                    overrides=dict(error_probability=2.5))
    assert get_history(store, car_id)[-1]["details"]["driver"] == custom["driver"]


def test_explicit_archetype_overrides_saved_driver(store):
    car_id = create_car(store, "Car", "F3", from_preset("F3"),
                        dict(archetype="HIGH_RISK", overrides=dict(aggression=0.1)))
    result = run_stress_test(store, car_id, n_races=N_RACES_FAST, base_seed=7,
                             driver_archetype="SMOOTH")
    assert result["driver"] == dict(archetype="SMOOTH", overrides={})
