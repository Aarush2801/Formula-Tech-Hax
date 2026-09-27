"""Authored circuits.

The primary circuit is fictional. That is deliberate: a fictional layout cannot
be mistaken for an assessment of a real, homologated venue, which is a claim this
prototype is in no position to make.

Nothing about Turn 7 is special-cased anywhere in the engine or the analyser. It
is simply the narrowest corner on the circuit, it follows a long braking zone
with a high overtaking rating, and it has the least runoff. Whether it actually
becomes a recurring hotspot is an output of the search, not an input to it.
"""

from __future__ import annotations

import math

from .models import Track
from .track import build_track

RAD = math.pi / 180.0


def _straight(name, length, width=15.0, overtaking=0.25, runoff=14.0, barrier=22.0,
              braking=False, target=95.0):
    return dict(
        name=name,
        type="BRAKING_ZONE" if braking else "STRAIGHT",
        length=length,
        width=width,
        turn_sign=0,
        radius=None,
        target_speed=target,
        overtaking_opportunity=overtaking,
        runoff_width=runoff,
        barrier_distance=barrier,
    )


def _corner(name, turn_number, radius, angle_deg, direction, width=14.0,
            overtaking=0.2, runoff=12.0, barrier=18.0):
    sign = 1 if direction == "left" else -1
    return dict(
        name=name,
        type="CORNER",
        length=radius * angle_deg * RAD,
        width=width,
        turn_sign=sign,
        radius=radius,
        turn_number=turn_number,
        overtaking_opportunity=overtaking,
        runoff_width=runoff,
        barrier_distance=barrier,
    )


# --------------------------------------------------------------------------
# Vale Park — primary circuit. Corner angles sum to a net 360 degrees.
#   lefts:  90 + 70 + 95 + 150 + 110 + 100 + 75 + 90 = 780
#   rights: 110 + 95 + 80 + 135                      = 420
#   net:    360
# --------------------------------------------------------------------------
VALE_PARK_SPEC = [
    _straight("Start / Finish Straight", 560.0, width=16.0, overtaking=0.35),
    _straight("Turn 1 Braking Zone", 165.0, width=16.0, overtaking=0.90, braking=True),
    _corner("Turn 1", 1, 80.0, 90.0, "left", width=15.0, overtaking=0.70,
            runoff=20.0, barrier=28.0),

    _straight("Turn 1 Exit", 105.0, width=14.0, overtaking=0.30),
    _straight("Turn 2 Braking Zone", 95.0, width=13.0, overtaking=0.55, braking=True),
    _corner("Turn 2", 2, 45.0, 110.0, "right", width=12.0, overtaking=0.45,
            runoff=8.0, barrier=12.0),

    _straight("Vale Back Straight", 395.0, width=15.0, overtaking=0.40),
    _straight("Turn 3 Braking Zone", 120.0, width=15.0, overtaking=0.70, braking=True),
    _corner("Turn 3", 3, 120.0, 70.0, "left", width=15.0, overtaking=0.45,
            runoff=18.0, barrier=26.0),

    _straight("Turn 3 Exit", 130.0, width=14.0, overtaking=0.25),
    _straight("Turn 4 Braking Zone", 70.0, width=14.0, overtaking=0.35, braking=True),
    _corner("Turn 4", 4, 60.0, 95.0, "left", width=13.5, overtaking=0.20,
            runoff=11.0, barrier=16.0),

    _straight("Turn 4 Exit", 160.0, width=14.0, overtaking=0.25),
    _straight("Turn 5 Braking Zone", 85.0, width=14.0, overtaking=0.40, braking=True),
    _corner("Turn 5", 5, 90.0, 95.0, "right", width=14.0, overtaking=0.30,
            runoff=14.0, barrier=20.0),

    _straight("Turn 5 Exit", 185.0, width=15.0, overtaking=0.30),
    _straight("Turn 6 Braking Zone", 150.0, width=15.0, overtaking=0.80, braking=True),
    _corner("Turn 6 Hairpin", 6, 35.0, 150.0, "left", width=13.0, overtaking=0.55,
            runoff=10.0, barrier=15.0),

    # Short squirt out of the hairpin straight into the narrowest corner on the
    # circuit. Cars arrive unsettled, close together, with little room to move.
    _straight("Turn 6 Exit", 95.0, width=13.0, overtaking=0.35),
    _straight("Turn 7 Braking Zone", 130.0, width=12.0, overtaking=0.75, braking=True),
    _corner("Turn 7", 7, 55.0, 110.0, "left", width=11.0, overtaking=0.60,
            runoff=6.0, barrier=9.0),

    _straight("Turn 7 Exit", 175.0, width=13.0, overtaking=0.25),
    _straight("Turn 8 Braking Zone", 60.0, width=14.0, overtaking=0.30, braking=True),
    _corner("Turn 8", 8, 150.0, 80.0, "right", width=14.0, overtaking=0.35,
            runoff=16.0, barrier=24.0),

    _straight("Turn 8 Exit", 245.0, width=15.0, overtaking=0.35),
    _straight("Turn 9 Braking Zone", 110.0, width=15.0, overtaking=0.65, braking=True),
    _corner("Turn 9", 9, 70.0, 100.0, "left", width=13.5, overtaking=0.40,
            runoff=12.0, barrier=17.0),

    _straight("Turn 9 Exit", 140.0, width=14.0, overtaking=0.25),
    _straight("Turn 10 Braking Zone", 125.0, width=14.0, overtaking=0.70, braking=True),
    _corner("Turn 10", 10, 40.0, 135.0, "right", width=12.5, overtaking=0.50,
            runoff=9.0, barrier=13.0),

    _straight("Turn 10 Exit", 190.0, width=15.0, overtaking=0.30),
    _straight("Turn 11 Braking Zone", 75.0, width=15.0, overtaking=0.35, braking=True),
    _corner("Turn 11", 11, 110.0, 75.0, "left", width=15.0, overtaking=0.30,
            runoff=18.0, barrier=25.0),

    _straight("Turn 11 Exit", 120.0, width=15.0, overtaking=0.25),
    _straight("Turn 12 Braking Zone", 80.0, width=16.0, overtaking=0.40, braking=True),
    _corner("Turn 12", 12, 95.0, 90.0, "left", width=16.0, overtaking=0.35,
            runoff=22.0, barrier=30.0),

    _straight("Turn 12 Exit onto Main Straight", 300.0, width=16.0, overtaking=0.30),
]

# --------------------------------------------------------------------------
# Kessel Ring — a shorter, faster secondary layout for cross-circuit comparison.
#   lefts:  120 + 90 + 80 + 130 = 420 ; rights: 60 = 60 ; net 360
# --------------------------------------------------------------------------
KESSEL_RING_SPEC = [
    _straight("Kessel Straight", 700.0, width=17.0, overtaking=0.40),
    _straight("Kessel T1 Braking", 180.0, width=17.0, overtaking=0.85, braking=True),
    _corner("Kessel Turn 1", 1, 50.0, 120.0, "left", width=14.0, overtaking=0.60,
            runoff=14.0, barrier=20.0),
    _straight("Kessel T1 Exit", 260.0, width=15.0, overtaking=0.30),
    _straight("Kessel T2 Braking", 90.0, width=15.0, overtaking=0.45, braking=True),
    _corner("Kessel Turn 2", 2, 140.0, 90.0, "left", width=15.0, overtaking=0.35,
            runoff=20.0, barrier=28.0),
    _straight("Kessel Esses Approach", 300.0, width=15.0, overtaking=0.30),
    _corner("Kessel Turn 3", 3, 180.0, 60.0, "right", width=14.0, overtaking=0.25,
            runoff=16.0, barrier=22.0),
    _straight("Kessel T3 Exit", 220.0, width=14.0, overtaking=0.30),
    _straight("Kessel T4 Braking", 140.0, width=14.0, overtaking=0.75, braking=True),
    _corner("Kessel Turn 4", 4, 55.0, 80.0, "left", width=12.0, overtaking=0.55,
            runoff=7.0, barrier=10.0),
    _straight("Kessel T4 Exit", 180.0, width=15.0, overtaking=0.25),
    _straight("Kessel T5 Braking", 100.0, width=16.0, overtaking=0.50, braking=True),
    _corner("Kessel Turn 5", 5, 85.0, 130.0, "left", width=16.0, overtaking=0.40,
            runoff=20.0, barrier=26.0),
    _straight("Kessel Final Run", 240.0, width=17.0, overtaking=0.30),
]

CIRCUIT_SPECS = {
    "vale_park": ("Vale Park Circuit", "Fictional", VALE_PARK_SPEC),
    "kessel_ring": ("Kessel Ring", "Fictional", KESSEL_RING_SPEC),
}

_cache: dict[tuple[str, float], Track] = {}


def get_track(track_id: str = "vale_park", width_multiplier: float = 1.0) -> Track:
    key = (track_id, round(width_multiplier, 4))
    if key not in _cache:
        if track_id not in CIRCUIT_SPECS:
            raise KeyError(f"unknown circuit '{track_id}'")
        name, country, spec = CIRCUIT_SPECS[track_id]
        _cache[key] = build_track(track_id, name, country, spec, width_multiplier)
    return _cache[key]


def list_tracks() -> list[dict]:
    out = []
    for tid in CIRCUIT_SPECS:
        t = get_track(tid)
        out.append(
            dict(
                id=t.id, name=t.name, country=t.country, length=round(t.length, 1),
                n_segments=len(t.segments), n_corners=len(t.corners),
                closure_error=round(getattr(t, "closure_error", 0.0), 3),
                min_width=round(min(s.width for s in t.segments), 2),
                max_width=round(max(s.width for s in t.segments), 2),
            )
        )
    return out
