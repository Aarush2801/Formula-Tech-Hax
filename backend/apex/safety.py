"""Surrogate safety analysis.

This module is the methodological core. It implements established surrogate
safety measures rather than a bespoke "danger score":

TTC (time to collision)
    Closed-form, from projected constant-velocity motion of two oriented boxes in
    the curvilinear track frame. A pair is in conflict at time t if their
    longitudinal extents overlap *and* their lateral extents overlap. Each
    condition is an interval in t; TTC is the start of the intersection of the two
    intervals, when that start is non-negative.

PET (post-encroachment time)
    Measured by cell occupancy, which is how PET is defined operationally: the
    track is diced into conflict cells and PET is the elapsed time between one
    vehicle clearing a cell and the next vehicle entering it. No trajectory
    projection is involved, so PET catches near-misses that TTC misses entirely
    (the classic case of two cars that were never on a collision course but
    occupied the same piece of track moments apart).

Conflict typing
    By the angle between the two vehicles' headings at minimum TTC, following
    SSAM's scheme: below ~30 deg rear-end, above ~85 deg crossing, in between a
    lane-change conflict. Racing-specific refinements (overtaking / defensive)
    are layered on top from the agents' recorded intent, and are clearly a
    prototype addition rather than part of SSAM.

What this module does NOT do
    It never converts a surrogate measure into a probability of a real-world
    crash. A low TTC means two simulated trajectories came close to intersecting
    under this model's assumptions. That is all it means.

Reference: FHWA Surrogate Safety Assessment Model, FHWA-HRT-08-049 and
FHWA-HRT-08-050.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import assumptions as A
from .models import ConflictType, Severity

INF = 1e9


# ==========================================================================
# TTC
# ==========================================================================
def _overlap_interval(p: np.ndarray, u: np.ndarray, c: float):
    """Interval of t for which |p + u*t| < c.

    Returns (lo, hi) with lo > hi meaning "never". Handles u ~ 0 by returning
    an unbounded interval when already overlapping and an empty one otherwise.
    """
    tiny = np.abs(u) < 1e-6
    safe_u = np.where(tiny, 1.0, u)
    ta = (-c - p) / safe_u
    tb = (c - p) / safe_u
    lo = np.minimum(ta, tb)
    hi = np.maximum(ta, tb)
    already = np.abs(p) < c
    lo = np.where(tiny, np.where(already, -INF, INF), lo)
    hi = np.where(tiny, np.where(already, INF, -INF), hi)
    return lo, hi


def pairwise_ttc(
    s: np.ndarray,
    d: np.ndarray,
    v: np.ndarray,
    lat_rate: np.ndarray,
    track_length: float,
    car_length: float = A.CAR_LENGTH,
    car_width: float = A.CAR_WIDTH,
) -> np.ndarray:
    """Full N x N matrix of time-to-collision in seconds (INF where no conflict).

    The matrix is symmetric. Diagonal is INF.
    """
    n = len(s)
    ds = s[None, :] - s[:, None]
    # Shortest signed distance around a closed loop.
    ds = (ds + track_length / 2.0) % track_length - track_length / 2.0
    dd = d[None, :] - d[:, None]
    dvs = v[None, :] - v[:, None]
    dvd = lat_rate[None, :] - lat_rate[:, None]

    lon_lo, lon_hi = _overlap_interval(ds, dvs, car_length)
    lat_lo, lat_hi = _overlap_interval(dd, dvd, car_width)

    lo = np.maximum(lon_lo, lat_lo)
    hi = np.minimum(lon_hi, lat_hi)

    ttc = np.where((lo <= hi) & (hi >= 0.0), np.maximum(lo, 0.0), INF)
    np.fill_diagonal(ttc, INF)
    return ttc


def ttc_from_relative(
    ds: np.ndarray, dd: np.ndarray, dvs: np.ndarray, dvd: np.ndarray,
    car_length: float = A.CAR_LENGTH, car_width: float = A.CAR_WIDTH,
) -> np.ndarray:
    """Same kernel as ``pairwise_ttc`` but taking relative quantities directly.

    The agents need this because what they act on is a *delayed* view of their
    neighbours, which exists only as relative matrices, never as a consistent set
    of absolute positions. Keeping the two paths on one kernel means the agents'
    notion of TTC and the analyser's are the same measure, differing only in the
    information each has access to.
    """
    lon_lo, lon_hi = _overlap_interval(ds, dvs, car_length)
    lat_lo, lat_hi = _overlap_interval(dd, dvd, car_width)
    lo = np.maximum(lon_lo, lat_lo)
    hi = np.minimum(lon_hi, lat_hi)
    ttc = np.where((lo <= hi) & (hi >= 0.0), np.maximum(lo, 0.0), INF)
    np.fill_diagonal(ttc, INF)
    return ttc


def closing_speed_matrix(
    s: np.ndarray, d: np.ndarray, v: np.ndarray, lat_rate: np.ndarray,
    track_length: float,
) -> np.ndarray:
    """Rate at which the gap between each pair is shrinking, in m/s.

    Projection of relative velocity onto the unit vector between the two cars,
    negated so that positive means closing.
    """
    ds = s[None, :] - s[:, None]
    ds = (ds + track_length / 2.0) % track_length - track_length / 2.0
    dd = d[None, :] - d[:, None]
    dist = np.hypot(ds, dd)
    dist = np.where(dist < 1e-6, 1e-6, dist)
    dvs = v[None, :] - v[:, None]
    dvd = lat_rate[None, :] - lat_rate[:, None]
    return -(ds * dvs + dd * dvd) / dist


def gap_matrix(s: np.ndarray, d: np.ndarray, track_length: float) -> np.ndarray:
    ds = s[None, :] - s[:, None]
    ds = (ds + track_length / 2.0) % track_length - track_length / 2.0
    dd = d[None, :] - d[:, None]
    return np.hypot(ds, dd)


# ==========================================================================
# PET
# ==========================================================================
class PETTracker:
    """Cell-occupancy post-encroachment time.

    One pass, O(N) per timestep. For each conflict cell we remember which car was
    last in it and when it left. When a *different* car enters that cell, the gap
    between those two instants is the PET for that pair at that location.
    """

    def __init__(self, track_length: float, n_cars: int):
        self.cell_len = A.PET_CELL_LENGTH
        self.cell_w = A.PET_CELL_WIDTH
        self.n_lon = max(int(math.ceil(track_length / self.cell_len)), 1)
        self.track_length = track_length
        # cell -> (car index, time last seen in that cell)
        self._last: dict[int, tuple[int, float]] = {}
        self._prev_cell = np.full(n_cars, -1, dtype=np.int64)
        # Recorded qualifying encroachments.
        self.events: list[dict] = []
        self.min_pet: float = INF
        self.pair_min: dict[tuple[int, int], tuple[float, float, int]] = {}

    def update(self, t: float, s: np.ndarray, d: np.ndarray,
               seg_idx: np.ndarray) -> None:
        lon = (np.floor((s % self.track_length) / self.cell_len)
               .astype(np.int64) % self.n_lon)
        lat = np.floor(d / self.cell_w).astype(np.int64)
        cell = lon * 64 + (lat + 32)

        for i in range(len(s)):
            c = int(cell[i])
            prev = self._last.get(c)
            if c != self._prev_cell[i]:
                # i has just entered cell c.
                if prev is not None and prev[0] != i:
                    pet = t - prev[1]
                    if 0.0 < pet <= A.PET_CONFLICT_THRESHOLD:
                        a, b = prev[0], i
                        key = (min(a, b), max(a, b))
                        cur = self.pair_min.get(key)
                        if cur is None or pet < cur[0]:
                            self.pair_min[key] = (pet, t, int(seg_idx[i]))
                        if pet < self.min_pet:
                            self.min_pet = pet
                        self.events.append(
                            dict(t=round(t, 3), pet=round(pet, 4),
                                 leader=int(a), follower=int(b),
                                 segment_index=int(seg_idx[i]))
                        )
                self._prev_cell[i] = c
            self._last[c] = (i, t)


# ==========================================================================
# Conflict typing and severity
# ==========================================================================
def classify_conflict_type(
    heading_a: float, heading_b: float, lat_rate_a: float, lat_rate_b: float,
    long_gap: float, overtaking: bool, defending: bool,
) -> ConflictType:
    """SSAM-style angle typing, with racing intent layered on top."""
    angle = abs(math.degrees(_wrap_angle(heading_a - heading_b)))
    if angle >= A.CONFLICT_ANGLE_CROSSING:
        return ConflictType.CROSSING

    lateral_activity = max(abs(lat_rate_a), abs(lat_rate_b))
    side_by_side = abs(long_gap) < A.CAR_LENGTH * 1.6

    # Racing-specific labels take precedence when intent was recorded, because
    # they carry more information than the geometric label alone.
    if overtaking and side_by_side:
        return ConflictType.OVERTAKING
    if defending and lateral_activity > 1.0:
        return ConflictType.DEFENSIVE
    if side_by_side:
        return ConflictType.SIDE_BY_SIDE
    if angle >= A.CONFLICT_ANGLE_REAR_END or lateral_activity > 2.0:
        return ConflictType.LANE_CHANGE
    return ConflictType.REAR_END


def _wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def classify_severity(
    min_ttc: float, min_pet: float | None, collision: bool, off_track: bool,
    spin: bool, max_decel: float, evasive: bool,
) -> Severity:
    if collision or spin or off_track:
        return Severity.INCIDENT
    critical_ttc = min_ttc <= A.TTC_CRITICAL_THRESHOLD
    critical_pet = min_pet is not None and min_pet <= A.PET_CRITICAL_THRESHOLD
    if critical_ttc or (critical_pet and evasive):
        return Severity.CRITICAL
    if (
        min_ttc <= A.TTC_CONFLICT_THRESHOLD
        or max_decel >= A.HARD_BRAKING_THRESHOLD
        or (min_pet is not None and min_pet <= A.PET_CONFLICT_THRESHOLD)
    ):
        return Severity.WARNING
    return Severity.NORMAL


def scsi(
    min_ttc: float, min_pet: float | None, closing_speed: float, max_decel: float
) -> float:
    """Simulation Conflict Severity Index.

    A CONSTRUCTED ranking aid, not a validated severity measure and not a crash
    probability. Weighted sum of four normalised surrogate measures, each clipped
    to [0, 1]:

        ttc_term   = 1 - min_ttc / TTC_CONFLICT_THRESHOLD
        pet_term   = 1 - min_pet / PET_CONFLICT_THRESHOLD   (0 if PET unmeasured)
        speed_term = closing_speed / SCSI_CLOSING_SPEED_REF
        decel_term = max_decel / SCSI_DECEL_REF

    Weights live in assumptions.SCSI_WEIGHTS and are shown in the UI wherever
    this index is displayed. Raw metrics are always displayed alongside it, and
    every ranked view can be switched to raw minimum TTC instead.
    """
    w = A.SCSI_WEIGHTS
    ttc_term = np.clip(1.0 - min_ttc / A.TTC_CONFLICT_THRESHOLD, 0.0, 1.0)
    if min_pet is None or min_pet >= INF:
        pet_term = 0.0
    else:
        pet_term = np.clip(1.0 - min_pet / A.PET_CONFLICT_THRESHOLD, 0.0, 1.0)
    speed_term = np.clip(closing_speed / A.SCSI_CLOSING_SPEED_REF, 0.0, 1.0)
    decel_term = np.clip(max_decel / A.SCSI_DECEL_REF, 0.0, 1.0)
    return float(
        w["ttc"] * ttc_term
        + w["pet"] * pet_term
        + w["closing_speed"] * speed_term
        + w["deceleration"] * decel_term
    )


def scsi_breakdown(min_ttc, min_pet, closing_speed, max_decel) -> dict:
    """Component-by-component decomposition, for the UI to show its construction."""
    w = A.SCSI_WEIGHTS
    terms = {
        "ttc": float(np.clip(1.0 - min_ttc / A.TTC_CONFLICT_THRESHOLD, 0.0, 1.0)),
        "pet": 0.0 if (min_pet is None or min_pet >= INF)
        else float(np.clip(1.0 - min_pet / A.PET_CONFLICT_THRESHOLD, 0.0, 1.0)),
        "closing_speed": float(np.clip(closing_speed / A.SCSI_CLOSING_SPEED_REF, 0.0, 1.0)),
        "deceleration": float(np.clip(max_decel / A.SCSI_DECEL_REF, 0.0, 1.0)),
    }
    return {
        "terms": terms,
        "weights": dict(w),
        "contributions": {k: round(terms[k] * w[k], 5) for k in terms},
        "total": round(sum(terms[k] * w[k] for k in terms), 5),
    }


# ==========================================================================
# Pairwise conflict accumulator
# ==========================================================================
@dataclass
class PairRecord:
    min_ttc: float = INF
    t_min_ttc: float = 0.0
    step_min_ttc: int = 0
    segment_at_min: int = 0
    max_closing: float = 0.0
    max_decel: float = 0.0
    evasive: bool = False
    collision: bool = False
    overtaking: bool = False
    defending: bool = False
    heading_a: float = 0.0
    heading_b: float = 0.0
    lat_a: float = 0.0
    lat_b: float = 0.0
    long_gap: float = 0.0
    a_decision: str = ""
    b_decision: str = ""
    samples: int = 0


class ConflictAccumulator:
    """Tracks, for every pair that ever enters the TTC filter, the worst moment.

    Keeping only the extremum per pair per run is what keeps a 10,000-run batch
    small: a run produces a handful of pair records, not a matrix per timestep.
    """

    def __init__(self):
        self.pairs: dict[tuple[int, int], PairRecord] = {}

    def observe(
        self, t: float, step: int, ttc: np.ndarray, closing: np.ndarray,
        decel: np.ndarray, lat_rate: np.ndarray, heading: np.ndarray,
        seg_idx: np.ndarray, gap_long: np.ndarray, overtaking: np.ndarray,
        defending: np.ndarray, decisions: list[str],
    ) -> None:
        cand = np.argwhere(ttc <= A.TTC_CONFLICT_THRESHOLD)
        for i, j in cand:
            if i >= j:
                continue
            key = (int(i), int(j))
            rec = self.pairs.get(key)
            if rec is None:
                rec = PairRecord()
                self.pairs[key] = rec
            rec.samples += 1
            c = float(closing[i, j])
            rec.max_closing = max(rec.max_closing, c)
            rec.max_decel = max(rec.max_decel, float(decel[i]), float(decel[j]))
            if abs(lat_rate[i]) >= A.EVASIVE_LATERAL_THRESHOLD or \
               abs(lat_rate[j]) >= A.EVASIVE_LATERAL_THRESHOLD or \
               max(float(decel[i]), float(decel[j])) >= A.EMERGENCY_BRAKING_THRESHOLD:
                rec.evasive = True
            rec.overtaking = rec.overtaking or bool(overtaking[i]) or bool(overtaking[j])
            rec.defending = rec.defending or bool(defending[i]) or bool(defending[j])
            tv = float(ttc[i, j])
            if tv < rec.min_ttc:
                rec.min_ttc = tv
                rec.t_min_ttc = t
                rec.step_min_ttc = step
                rec.segment_at_min = int(seg_idx[i])
                rec.heading_a = float(heading[i])
                rec.heading_b = float(heading[j])
                rec.lat_a = float(lat_rate[i])
                rec.lat_b = float(lat_rate[j])
                rec.long_gap = float(gap_long[i, j])
                rec.a_decision = decisions[i]
                rec.b_decision = decisions[j]

    def mark_collision(self, i: int, j: int) -> None:
        key = (min(i, j), max(i, j))
        rec = self.pairs.get(key)
        if rec is None:
            rec = PairRecord(min_ttc=0.0)
            self.pairs[key] = rec
        rec.collision = True
        rec.min_ttc = 0.0
