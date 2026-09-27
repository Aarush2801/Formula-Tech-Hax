"""Surrogate safety measures, checked against hand calculations.

These are the numbers every claim in the dashboard rests on, so they are tested
against closed-form answers computed independently rather than against recorded
output.
"""

import math

import numpy as np
import pytest

from apex import assumptions as A
from apex.safety import (PETTracker, classify_conflict_type, classify_severity,
                         closing_speed_matrix, gap_matrix, pairwise_ttc, scsi,
                         scsi_breakdown, ttc_from_relative, INF)
from apex.models import ConflictType, Severity

L = 5000.0


def test_rear_end_ttc_matches_closed_form():
    # Follower at s=60 doing 80 m/s, leader at s=100 doing 50 m/s.
    # Boxes touch when the 40 m centre gap closes to one car length.
    s = np.array([60.0, 100.0]); d = np.zeros(2)
    v = np.array([80.0, 50.0]); lat = np.zeros(2)
    ttc = pairwise_ttc(s, d, v, lat, L)
    expected = (40.0 - A.CAR_LENGTH) / 30.0
    assert ttc[0, 1] == pytest.approx(expected, rel=1e-9)
    assert ttc[1, 0] == pytest.approx(expected, rel=1e-9), "matrix must be symmetric"
    assert ttc[0, 0] == INF and ttc[1, 1] == INF, "diagonal must be INF"


def test_no_conflict_when_laterally_separated_and_not_converging():
    s = np.array([60.0, 100.0]); d = np.array([0.0, 6.0])
    v = np.array([80.0, 50.0]); lat = np.zeros(2)
    assert pairwise_ttc(s, d, v, lat, L)[0, 1] == INF


def test_lateral_only_convergence():
    # Same arc position, converging laterally at 4 m/s from 8 m apart.
    s = np.array([100.0, 100.0]); d = np.array([0.0, 8.0])
    v = np.array([70.0, 70.0]); lat = np.array([2.0, -2.0])
    ttc = pairwise_ttc(s, d, v, lat, L)
    assert ttc[0, 1] == pytest.approx((8.0 - A.CAR_WIDTH) / 4.0)


def test_already_overlapping_gives_zero_ttc():
    s = np.array([100.0, 102.0]); d = np.array([0.0, 0.5])
    v = np.array([70.0, 70.0]); lat = np.zeros(2)
    assert pairwise_ttc(s, d, v, lat, L)[0, 1] == 0.0


def test_diverging_pair_has_no_ttc():
    s = np.array([60.0, 100.0]); d = np.zeros(2)
    v = np.array([50.0, 80.0]); lat = np.zeros(2)  # leader pulling away
    assert pairwise_ttc(s, d, v, lat, L)[0, 1] == INF


def test_ttc_wraps_around_the_lap():
    # Car 0 just before the line, car 1 just after: the gap is 20 m, not 4980 m.
        s = np.array([L - 10.0, 10.0]); d = np.zeros(2)
        v = np.array([60.0, 40.0]); lat = np.zeros(2)
        ttc = pairwise_ttc(s, d, v, lat, L)
        assert ttc[0, 1] == pytest.approx((20.0 - A.CAR_LENGTH) / 20.0)


def test_relative_form_agrees_with_absolute_form():
    rng = np.random.default_rng(7)
    s = rng.uniform(0, L, 8); d = rng.uniform(-6, 6, 8)
    v = rng.uniform(30, 90, 8); lat = rng.uniform(-4, 4, 8)
    absolute = pairwise_ttc(s, d, v, lat, L)
    ds = (s[None, :] - s[:, None] + L / 2) % L - L / 2
    dd = d[None, :] - d[:, None]
    dvs = v[None, :] - v[:, None]
    dvd = lat[None, :] - lat[:, None]
    relative = ttc_from_relative(ds, dd, dvs, dvd)
    assert np.allclose(absolute, relative, equal_nan=True)


def test_closing_speed_sign_and_magnitude():
    s = np.array([60.0, 100.0]); d = np.zeros(2)
    v = np.array([80.0, 50.0]); lat = np.zeros(2)
    cs = closing_speed_matrix(s, d, v, lat, L)
    assert cs[0, 1] == pytest.approx(30.0), "positive means closing"
    v2 = np.array([50.0, 80.0])
    assert closing_speed_matrix(s, d, v2, lat, L)[0, 1] == pytest.approx(-30.0)


def test_gap_matrix_is_euclidean_in_track_frame():
    s = np.array([0.0, 30.0]); d = np.array([0.0, 4.0])
    assert gap_matrix(s, d, L)[0, 1] == pytest.approx(math.hypot(30.0, 4.0))


# --------------------------------------------------------------------------
# PET
# --------------------------------------------------------------------------
def test_pet_measures_gap_between_cell_occupancies():
    """Car 0 clears a cell, car 1 enters it 0.4 s later: PET is 0.4 s."""
    pet = PETTracker(L, 2)
    cell = A.PET_CELL_LENGTH
    seg = np.array([0, 0])
    # Car 0 sits in cell 10 then leaves; car 1 arrives shortly after.
    pet.update(0.0, np.array([10 * cell + 1, 10 * cell - 40]), np.zeros(2), seg)
    pet.update(0.1, np.array([10 * cell + 1, 10 * cell - 30]), np.zeros(2), seg)
    pet.update(0.2, np.array([11 * cell + 1, 10 * cell - 20]), np.zeros(2), seg)
    pet.update(0.5, np.array([12 * cell + 1, 10 * cell + 1]), np.zeros(2), seg)
    assert pet.min_pet == pytest.approx(0.4, abs=1e-6)
    assert (0, 1) in pet.pair_min


def test_pet_ignores_a_car_re_entering_its_own_cell():
    pet = PETTracker(L, 1)
    cell = A.PET_CELL_LENGTH
    for i, s in enumerate([1.0, 1.0, cell + 1, 1.0]):
        pet.update(i * 0.1, np.array([s]), np.zeros(1), np.array([0]))
    assert pet.min_pet == INF, "a single car cannot conflict with itself"


def test_pet_respects_the_conflict_threshold():
    pet = PETTracker(L, 2)
    cell = A.PET_CELL_LENGTH
    seg = np.array([0, 0])
    pet.update(0.0, np.array([10 * cell + 1, 0.0]), np.zeros(2), seg)
    pet.update(0.1, np.array([12 * cell + 1, 0.0]), np.zeros(2), seg)
    # Car 1 arrives long after the PET threshold has passed.
    t_late = A.PET_CONFLICT_THRESHOLD + 2.0
    pet.update(t_late, np.array([20 * cell, 10 * cell + 1]), np.zeros(2), seg)
    assert pet.min_pet == INF


# --------------------------------------------------------------------------
# Typing, severity, index
# --------------------------------------------------------------------------
def test_conflict_typing_follows_heading_angle():
    # Nearly parallel, one behind the other -> rear-end.
    assert classify_conflict_type(0.0, 0.05, 0.0, 0.0, 30.0, False, False) \
        == ConflictType.REAR_END
    # Large heading difference -> crossing, regardless of intent.
    big = math.radians(A.CONFLICT_ANGLE_CROSSING + 10)
    assert classify_conflict_type(0.0, big, 0.0, 0.0, 30.0, True, True) \
        == ConflictType.CROSSING
    # Alongside with overtake intent -> overtaking.
    assert classify_conflict_type(0.0, 0.02, 1.0, 0.0, 2.0, True, False) \
        == ConflictType.OVERTAKING
    # Alongside without intent -> side by side.
    assert classify_conflict_type(0.0, 0.02, 0.0, 0.0, 2.0, False, False) \
        == ConflictType.SIDE_BY_SIDE


def test_severity_ladder():
    assert classify_severity(0.05, None, True, False, False, 40, True) == Severity.INCIDENT
    assert classify_severity(0.5, None, False, False, False, 10, False) == Severity.CRITICAL
    assert classify_severity(1.2, None, False, False, False, 10, False) == Severity.WARNING
    assert classify_severity(9.0, None, False, False, False, 1, False) == Severity.NORMAL
    # An off-track excursion is an incident even with a comfortable TTC.
    assert classify_severity(9.0, None, False, True, False, 1, False) == Severity.INCIDENT


def test_scsi_is_bounded_and_monotonic_in_ttc():
    lo = scsi(1.4, 4.0, 5.0, 5.0)
    hi = scsi(0.1, 0.2, 50.0, 44.0)
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0
    assert hi > lo
    # Monotone decreasing in TTC, all else equal.
    vals = [scsi(t, 1.0, 20.0, 20.0) for t in (0.2, 0.6, 1.0, 1.4)]
    assert vals == sorted(vals, reverse=True)


def test_scsi_breakdown_sums_to_total():
    bd = scsi_breakdown(0.71, 0.48, 11.4, 40.0)
    assert bd["total"] == pytest.approx(sum(bd["contributions"].values()), abs=1e-9)
    assert bd["total"] == pytest.approx(scsi(0.71, 0.48, 11.4, 40.0), abs=1e-5)
    assert sum(bd["weights"].values()) == pytest.approx(1.0)


def test_scsi_ignores_unmeasured_pet():
    assert scsi(1.0, None, 10.0, 10.0) == pytest.approx(scsi(1.0, INF, 10.0, 10.0))
