"""Apex Passport step 3: wear conversion.

Converts one simulated race's team-car telemetry (kerb strikes, contacts)
into a predicted increment of % life used per part. This is a labelled
modelling choice (see the "Apex Passport" group in assumptions.py), not a
measured wear curve -- its job is to give the stress test something concrete
to aggregate across many simulated races, with two properties the spec asks
for explicitly: harder hits cost much more life (a severity-squared /
speed-linear term, not a flat per-event cost), and load is shared between the
parts on the side that was actually struck rather than smeared across all
four corners.
"""
from __future__ import annotations

from . import assumptions as A

SUSPENSION_LEFT = ("suspension_fl", "suspension_rl")
SUSPENSION_RIGHT = ("suspension_fr", "suspension_rr")

assert abs(A.CONTACT_WEAR_SUSPENSION_SHARE + A.CONTACT_WEAR_WHEEL_SHARE
          + A.CONTACT_WEAR_BRAKE_SHARE - 1.0) < 1e-9, (
    "contact wear shares must sum to 1.0 -- see assumptions.py"
)


def _add(totals: dict[str, float], part: str, amount: float) -> None:
    totals[part] = totals.get(part, 0.0) + amount


def wear_from_kerb_strike(strike: dict) -> dict[str, float]:
    severity = float(strike.get("severity", 0.0))
    total = A.KERB_WEAR_BASE_PCT + A.KERB_WEAR_SEVERITY_GAIN * severity ** 2
    wheel = total * A.KERB_WEAR_WHEEL_SHARE
    per_corner = (total - wheel) / 2.0
    side_parts = SUSPENSION_LEFT if strike.get("lateral_offset", 0.0) >= 0 else SUSPENSION_RIGHT
    return {side_parts[0]: per_corner, side_parts[1]: per_corner, "wheels": wheel}


def wear_from_contact(contact: dict) -> dict[str, float]:
    speed = float(contact.get("impact_speed", 0.0))
    total = A.CONTACT_WEAR_BASE_PCT + A.CONTACT_WEAR_SPEED_GAIN * speed
    if contact.get("severe"):
        total *= A.CONTACT_WEAR_SEVERE_MULTIPLIER
    suspension_total = total * A.CONTACT_WEAR_SUSPENSION_SHARE
    wheel = total * A.CONTACT_WEAR_WHEEL_SHARE
    brake = total * A.CONTACT_WEAR_BRAKE_SHARE
    per_corner = suspension_total / 2.0
    side_parts = SUSPENSION_LEFT if contact.get("side") == "left" else SUSPENSION_RIGHT
    return {side_parts[0]: per_corner, side_parts[1]: per_corner,
           "wheels": wheel, "brakes": brake}


def wear_for_race(team_car_telemetry: dict | None) -> dict[str, float]:
    """Total predicted % life used, per part, for one simulated race.
    Every part in PASSPORT_PARTS is present, at 0.0 if untouched."""
    totals: dict[str, float] = {p: 0.0 for p in A.PASSPORT_PARTS}
    if not team_car_telemetry:
        return totals
    for strike in team_car_telemetry.get("kerb_strikes", []):
        for part, wear in wear_from_kerb_strike(strike).items():
            _add(totals, part, wear)
    for contact in team_car_telemetry.get("contacts", []):
        for part, wear in wear_from_contact(contact).items():
            _add(totals, part, wear)
    return totals


def estimated_repair_cost(team_car_telemetry: dict | None) -> float:
    """Illustrative repair cost for one race's recorded contacts."""
    if not team_car_telemetry:
        return 0.0
    cost = 0.0
    for contact in team_car_telemetry.get("contacts", []):
        cost += (A.CONTACT_REPAIR_COST_SEVERE if contact.get("severe")
                else A.CONTACT_REPAIR_COST_LIGHT)
    return cost
