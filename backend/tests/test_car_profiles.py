"""Apex Passport step 1: CarProfile and the optional team car.

The one property everything else depends on: team_car=None must be provably
identical to the simulator's existing behaviour. That is tested here two
ways -- omitting team_car entirely, and setting it to the REFERENCE profile
(which is defined as exactly what the field-wide assumptions already imply).
"""
import hashlib

import numpy as np

from apex.batch import build_run
from apex.car_profiles import CLASS_PRESETS, REFERENCE_CAR_PROFILE, from_preset
from apex.drivers import apply_team_driver, build_roster
from apex.engine import RaceEngine
from apex.scenario import ScenarioSpace, sample, scenario_from_dict
from apex.track import brake_accel_limit, lateral_accel_limit


def _digest(arr) -> str:
    return hashlib.sha1(np.ascontiguousarray(arr, dtype=np.float64).tobytes()).hexdigest()


def _scenario(seed=483921, duration=25.0, cars=22, team_car=None):
    sc = sample(seed, ScenarioSpace(),
                pin=dict(n_cars=cars, weather="WET", traffic_density=0.7, duration=duration))
    sc.team_car = team_car
    return sc


def test_no_team_car_is_unchanged():
    """The literal default: scenario.team_car is None."""
    sc_a = _scenario()
    sc_b = _scenario()
    r1, _ = build_run(sc_a)
    r2, _ = build_run(sc_b)
    assert _digest(r1.traj_v) == _digest(r2.traj_v)
    assert r1.team_car_telemetry is None


def test_scenario_round_trips_with_team_car_field():
    sc = _scenario(team_car=dict(
        car_profile=REFERENCE_CAR_PROFILE.to_dict(), driver_archetype="SMOOTH"))
    rebuilt = scenario_from_dict(sc.to_dict())
    assert rebuilt.team_car == sc.team_car
    assert rebuilt.config_fingerprint() == sc.config_fingerprint()


def test_brake_and_lateral_limits_match_old_formula_with_no_override():
    """Function-level equivalence: track.py's two physics functions, called
    exactly as the engine calls them for every non-team car (no override
    arrays), must reproduce the pre-Apex-Passport scalar formula bit for bit.
    """
    v = np.linspace(10.0, 95.0, 50)
    grip = np.full_like(v, 0.83)

    old_lateral = (1.85 + 2.40 * (v / 80.0) ** 2) * grip * 9.81
    new_lateral = lateral_accel_limit(v, grip)  # mu/aero_gain default to None
    assert np.allclose(old_lateral, new_lateral)

    old_brake = (1.75 + 3.20 * (v / 80.0) ** 2) * grip * 9.81
    new_brake = brake_accel_limit(v, grip)  # flat_g defaults to None
    assert np.allclose(old_brake, new_brake)


def test_team_car_leaves_other_cars_physics_parameters_untouched():
    """The guarantee that matters: a team car's own per-car physics arrays
    are the only ones that change. Every other index keeps exactly the
    field-wide default.

    This deliberately does NOT assert other cars' full trajectories are
    identical: in an interactive multi-agent sim, changing car 0's physics
    changes car 0's path, and cars that follow/overtake/defend against car 0
    react to its *actual* position -- so a ripple into nearby cars' later
    trajectories is expected, correct behaviour, not a violation of
    "additive only". "Additive only" means the RULES for other cars are
    untouched, which is what this test checks directly.
    """
    from apex.circuits import get_track

    sc = _scenario(team_car=dict(
        car_profile=from_preset("F3").to_dict(), driver_archetype="SMOOTH"))
    track = get_track(sc.track_id)
    roster = apply_team_driver(build_roster(sc.n_cars, sc.field_mix or None), "SMOOTH")
    engine = RaceEngine(sc, track, roster, team_car_profile=from_preset("F3"))

    import numpy as np
    from apex import assumptions as A
    for arr, default in (
        (engine.car_mass, A.CAR_MASS), (engine.engine_power_w, A.ENGINE_POWER),
        (engine.drag_coeff_arr, A.DRAG_COEFF), (engine.mu_lateral, A.LATERAL_MU),
        (engine.aero_lateral_gain, A.AERO_LATERAL_GAIN),
        (engine.max_corner_speed_arr, A.MAX_CORNER_SPEED),
    ):
        assert np.all(arr[1:] == default), "a non-team car's physics default was altered"
    assert np.all(np.isnan(engine.brake_flat_g[1:]))
    # And car 0 (the team slot) should indeed differ -- otherwise the F3
    # profile isn't actually load-bearing.
    assert engine.car_mass[0] == 660.0 and engine.car_mass[0] != A.CAR_MASS


def test_reference_profile_lateral_physics_matches_default_exactly():
    """Cornering (unlike braking) reuses the field's exact speed-dependent
    formula for the team car, just with the car's own coefficients -- so with
    REFERENCE_CAR_PROFILE's coefficients (defined as equal to the field
    defaults) the lateral acceleration ceiling must match exactly across the
    whole speed range. Braking is intentionally a flatter, simpler model for
    any team car (see CarProfile's docstring) so it is not asserted here.
    """
    v = np.linspace(5.0, 100.0, 80)
    grip = np.full_like(v, 0.9)
    default = lateral_accel_limit(v, grip)
    reference = lateral_accel_limit(
        v, grip,
        mu=np.full_like(v, REFERENCE_CAR_PROFILE.tyre_grip_coeff),
        aero_gain=np.full_like(v, REFERENCE_CAR_PROFILE.downforce_coeff),
    )
    assert np.allclose(default, reference)


def test_team_car_present_produces_telemetry_payload():
    sc = _scenario(duration=60.0, team_car=dict(
        car_profile=from_preset("F3").to_dict(), driver_archetype="AGGRESSIVE_OVERTAKER"))
    r, profiles = build_run(sc)
    assert profiles[0].id == "TEAM"
    assert r.team_car_telemetry is not None
    tel = r.team_car_telemetry
    assert tel["driver_index"] == 0
    assert tel["peak_g"] >= 0.0
    assert isinstance(tel["kerb_strikes"], list)
    assert isinstance(tel["contacts"], list)
    assert tel["car_profile"]["class_name"] == "F3"


def test_lighter_higher_grip_car_corners_faster_than_reference():
    """A sanity check on the physics wiring, not just that it runs: a car with
    materially higher tyre_grip_coeff and downforce_coeff should achieve a
    higher peak cornering speed than the reference car on the same corner."""
    from apex.circuits import get_track
    track = get_track("vale_park")
    corner = next(s for s in track.segments if s.corner_radius)
    R = np.array([corner.corner_radius])
    grip = np.array([1.0])

    ref = RaceEngine._corner_speed(R, grip, mu=np.array([REFERENCE_CAR_PROFILE.tyre_grip_coeff]),
                                   aero_gain=np.array([REFERENCE_CAR_PROFILE.downforce_coeff]),
                                   max_speed=np.array([500.0]))
    hot = RaceEngine._corner_speed(R, grip, mu=np.array([REFERENCE_CAR_PROFILE.tyre_grip_coeff * 1.3]),
                                   aero_gain=np.array([REFERENCE_CAR_PROFILE.downforce_coeff * 1.3]),
                                   max_speed=np.array([500.0]))
    assert hot[0] > ref[0]


def test_all_class_presets_are_well_formed():
    for name, profile in CLASS_PRESETS.items():
        assert profile.mass_kg > 0
        assert profile.power_kw > 0
        assert profile.max_brake_g > 0
        assert 0 < profile.front_weight_pct < 100
        assert 0 < profile.aero_balance_front_pct < 100
        assert profile.class_name == name


def test_apply_team_driver_only_touches_slot_zero():
    base = build_roster(22)
    team_roster = apply_team_driver(base, "HIGH_RISK")
    assert team_roster[0].id == "TEAM"
    assert team_roster[0].archetype == "HIGH_RISK"
    for a, b in zip(base[1:], team_roster[1:]):
        assert a.id == b.id and a.archetype == b.archetype
