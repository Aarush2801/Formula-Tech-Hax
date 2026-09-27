"""Engine behaviour and physical plausibility.

Not a validation suite — there is nothing to validate against. These tests assert
that the model behaves the way its own documentation says it does, and that its
outputs stay inside physically sensible bounds, so that a regression in the
decision logic shows up as a failing test rather than as a quietly wrong dashboard.
"""

import numpy as np
import pytest

from apex import assumptions as A
from apex.batch import build_run
from apex.circuits import get_track, list_tracks
from apex.engine import RaceEngine
from apex.environment import make_environment, perception_range
from apex.errors import ERROR_KINDS, ErrorState
from apex.scenario import ScenarioSpace, sample
from apex.track import (TrackGeometry, brake_accel_limit, build_zones,
                        corner_speed, lateral_accel_limit)

G = 9.81


def _run(**pin):
    base = dict(n_cars=22, weather="DRY", traffic_density=0.6, duration=40.0)
    base.update(pin)
    return build_run(sample(20250926, ScenarioSpace(), pin=base))[0]


# --------------------------------------------------------------------------
# Track
# --------------------------------------------------------------------------
def test_every_circuit_closes():
    for t in list_tracks():
        assert t["closure_error"] < 0.5, f"{t['id']} does not close"


def test_corner_speeds_are_ordered_by_radius_and_grip():
    speeds = [corner_speed(r) for r in (35, 55, 80, 120, 150)]
    assert speeds == sorted(speeds), "tighter corners must be slower"
    for r in (35, 55, 80, 120):
        assert corner_speed(r, 0.7) < corner_speed(r, 1.0), "less grip, less speed"


def test_grip_limits_are_in_a_plausible_range():
    # Peak deceleration near top speed should be of the order of 5 g, and low-speed
    # grip should fall back toward mechanical levels.
    assert 4.0 < brake_accel_limit(85.0, 1.0) / G < 7.0
    assert 1.5 < brake_accel_limit(20.0, 1.0) / G < 2.6
    assert lateral_accel_limit(85.0, 1.0) > lateral_accel_limit(30.0, 1.0)


def test_racing_line_stays_inside_the_track():
    track = get_track()
    geo = TrackGeometry(track)
    s = np.linspace(0, track.length, 2000)
    line = geo.racing_line(s)
    half = geo.width(s) / 2
    assert np.all(np.abs(line) <= half - A.CAR_WIDTH * 0.5 + 1e-6)


def test_racing_line_apexes_toward_the_inside():
    track = get_track()
    geo = TrackGeometry(track)
    for seg in track.corners:
        d_apex = float(geo.racing_line(np.array([seg.s_mid]))[0])
        assert np.sign(d_apex) == np.sign(seg.curvature), (
            f"{seg.name}: apex on the wrong side")


def test_curvilinear_to_cartesian_round_trips_along_the_centreline():
    track = get_track()
    geo = TrackGeometry(track)
    s = np.linspace(5, track.length - 5, 500)
    x, y = geo.to_cartesian(s, np.zeros_like(s))
    # Consecutive centreline points must be about one step apart.
    step = np.hypot(np.diff(x), np.diff(y))
    expected = s[1] - s[0]
    assert np.all(np.abs(step - expected) < expected * 0.05)


def test_zones_cover_every_segment_exactly_once():
    track = get_track()
    z = build_zones(track)
    assert len(z["segment_to_zone"]) == len(track.segments)
    covered = sorted(i for zz in z["zones"].values() for i in zz["segment_indices"])
    assert covered == list(range(len(track.segments)))
    assert set(z["zones"]) == {c.turn_number for c in track.corners}


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
def test_weather_severity_is_monotonic():
    envs = [make_environment(w, jitter=False)
            for w in ("DRY", "DAMP", "WET", "HEAVY_RAIN")]
    grips = [e.grip for e in envs]
    vis = [e.visibility for e in envs]
    spray = [e.spray for e in envs]
    assert grips == sorted(grips, reverse=True)
    assert vis == sorted(vis, reverse=True)
    assert spray == sorted(spray)
    ranges = [perception_range(e) for e in envs]
    assert ranges == sorted(ranges, reverse=True)


def test_tyre_wear_reduces_grip():
    fresh = make_environment("DRY", tyre_condition=1.0, jitter=False)
    worn = make_environment("DRY", tyre_condition=0.0, jitter=False)
    assert worn.grip < fresh.grip


# --------------------------------------------------------------------------
# Human error
# --------------------------------------------------------------------------
def test_error_rates_land_near_their_configured_values():
    n, exposures = 200, 400
    es = ErrorState(n, np.ones(n), 1.0)
    rng = np.random.default_rng(11)
    in_corner = np.ones(n, dtype=bool)
    for k in range(exposures):
        es.sample_per_second(float(k), rng, in_corner)
        es.expire(float(k))
    counts = es.total_counts()
    for kind in ("delayed_reaction", "unexpected_line_change", "grip_loss"):
        observed = counts[kind] / (n * exposures)
        expected = A.ERROR_RATES[kind]
        assert observed == pytest.approx(expected, rel=0.25), kind


def test_error_multiplier_scales_error_counts():
    def total(mult):
        n = 200
        es = ErrorState(n, np.ones(n), mult)
        rng = np.random.default_rng(5)
        for k in range(200):
            es.sample_per_second(float(k), rng, np.ones(n, dtype=bool))
            es.expire(float(k))
        return sum(es.total_counts().values())
    assert total(2.0) > 1.5 * total(1.0) > 2.0 * total(0.25)


def test_errors_expire_and_clear_their_effects():
    es = ErrorState(4, np.ones(4) * 40.0, 1.0)  # very high rate, fires immediately
    rng = np.random.default_rng(3)
    es.sample_per_second(0.0, rng, np.ones(4, dtype=bool))
    assert es._any_active
    es.expire(100.0)
    assert np.all(es.braking_offset == 0.0)
    assert np.all(es.grip_scale == 1.0)
    assert np.all(es.reaction_scale == 1.0)
    assert np.all(es.line_bias == 0.0)
    assert not es.spinning.any()


# --------------------------------------------------------------------------
# Engine invariants
# --------------------------------------------------------------------------
def test_state_stays_physically_bounded():
    r = _run()
    assert np.all(r.traj_v > 0), "no car should stop dead"
    assert r.traj_v.max() < 110.0, "top speed must stay bounded"
    assert np.all(np.isfinite(r.traj_s)) and np.all(np.isfinite(r.traj_d))
    track = get_track()
    assert np.all(r.traj_s >= 0) and np.all(r.traj_s < track.length + 1)
    # Lateral position must stay within the track plus its runoff.
    assert np.abs(r.traj_d).max() < 40.0
    assert r.max_deceleration / G < 8.0, "deceleration beyond any plausible limit"


def test_cars_make_progress_around_the_lap():
    r = _run()
    assert r.laps_completed > 0.3, "the field should cover meaningful distance"
    track = get_track()
    mean_speed = r.traj_v.mean()
    assert 25.0 < mean_speed < 80.0, f"implausible mean speed {mean_speed:.1f} m/s"


def test_conflicts_are_consistent_with_their_metrics():
    r = _run(traffic_density=0.85)
    for c in r.conflicts:
        assert c["min_ttc"] <= A.TTC_CONFLICT_THRESHOLD + 1e-9
        assert c["min_ttc"] >= 0.0
        assert c["max_deceleration"] >= 0.0
        assert 0.0 <= c["scsi"] <= 1.0
        if c["collision"]:
            assert c["min_ttc"] == 0.0
            assert c["severity"] == "INCIDENT"
        assert c["driver_a_index"] != c["driver_b_index"]
        assert c["severity"] in ("WARNING", "CRITICAL", "INCIDENT")


def test_warmup_is_excluded_from_accounting():
    r = _run()
    for c in r.conflicts:
        assert c["t_min_ttc"] >= A.WARMUP - 1e-6, (
            "a conflict was counted inside the warm-up window")


def test_traffic_density_raises_conflict_counts():
    low = _run(traffic_density=0.15, n_cars=22)
    high = _run(traffic_density=0.95, n_cars=22)
    assert len(high.conflicts) > len(low.conflicts)


def test_more_cars_produce_more_conflicts():
    small = _run(n_cars=6, traffic_density=0.7)
    full = _run(n_cars=22, traffic_density=0.7)
    assert len(full.conflicts) >= len(small.conflicts)


def test_wet_conditions_increase_off_track_excursions():
    """Grip must have a visible physical consequence somewhere."""
    dry = 0
    wet = 0
    for seed in range(6):
        d = build_run(sample(seed + 100, ScenarioSpace(), pin=dict(
            n_cars=22, weather="DRY", traffic_density=0.6, duration=40.0)))[0]
        w = build_run(sample(seed + 100, ScenarioSpace(), pin=dict(
            n_cars=22, weather="HEAVY_RAIN", traffic_density=0.6, duration=40.0)))[0]
        dry += d.n_off_track
        wet += w.n_off_track
    assert wet > dry, f"wet {wet} should exceed dry {dry} excursions"


def test_contact_is_rare_in_benign_conditions():
    total = 0
    for seed in range(8):
        r = build_run(sample(seed + 500, ScenarioSpace(), pin=dict(
            n_cars=10, weather="DRY", traffic_density=0.2, duration=40.0,
            error_rate_multiplier=0.4)))[0]
        total += r.n_collisions
    assert total <= 2, f"{total} collisions in 8 benign runs is too many"


def test_agents_attempt_and_sometimes_complete_overtakes():
    r = _run(traffic_density=0.75)
    assert r.n_overtake_attempts > 0
    assert r.n_overtakes_completed > 0, "no pass ever completed"
    assert r.n_overtakes_completed <= r.n_overtake_attempts


def test_reaction_time_delay_is_actually_applied():
    """An agent's perception buffer must be long enough for its reaction time."""
    sc = sample(1, ScenarioSpace(), pin=dict(n_cars=22, duration=10.0))
    eng = RaceEngine(sc, get_track(), __import__(
        "apex.drivers", fromlist=["build_roster"]).build_roster(22))
    max_delay_steps = 0.45 * A.ERROR_EFFECTS["delayed_reaction_multiplier"] / A.DT
    assert eng.buf_len > max_delay_steps


def test_trajectories_are_recorded_for_every_step_and_car():
    r = _run(duration=20.0)
    assert r.traj_s.shape == (r.n_steps, 22)
    for arr in (r.traj_v, r.traj_d, r.traj_a, r.traj_brake, r.traj_throttle,
                r.traj_lat, r.traj_seg, r.traj_decision):
        assert arr.shape == (r.n_steps, 22)
    assert np.all(r.traj_brake >= 0) and np.all(r.traj_brake <= 1.0 + 1e-6)
    assert np.all(r.traj_throttle >= 0) and np.all(r.traj_throttle <= 1.0 + 1e-6)


def test_events_reference_valid_drivers_and_segments():
    r = _run(traffic_density=0.8)
    n_seg = len(get_track().segments)
    ids = {p.id for p in r.profiles}
    for e in r.events:
        assert 0 <= e["segment_index"] < n_seg
        assert e["driver_a"] in ids
        if e["driver_b"]:
            assert e["driver_b"] in ids
        assert e["t"] >= 0.0
