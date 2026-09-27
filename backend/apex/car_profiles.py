"""Apex Passport: car profiles.

A ``CarProfile`` is the technical specification of one physical car, used by
the (optional) team car in the engine's simple point-mass model:

  * cornering is limited by grip x (mechanical + aerodynamic downforce term),
    the same functional form as the field's own cornering limit
    (see ``track.lateral_accel_limit``), with the car's own coefficients;
  * acceleration comes from power minus drag, capped by a traction ceiling;
  * braking comes from ``max_brake_g`` x grip x weather -- deliberately a
    flat g-figure rather than the field's speed-dependent aero formula,
    because that is the figure a real technical passport would actually
    carry, and it keeps the team car's braking model legible on its own.

Every numeric value here is a labelled assumption or an illustrative class
preset, in the same spirit as ``assumptions.py``: none of it is manufacturer
data, and none of it should be presented as such.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import assumptions as A

G = 9.81


@dataclass
class CarProfile:
    """A car's technical specification. All fields are simulation inputs."""

    mass_kg: float                      # includes driver
    front_weight_pct: float             # front axle share of mass_kg, 0-100
    cg_height_m: float
    power_kw: float
    top_speed_kmh: float
    tyre_grip_coeff: float              # effective lateral/longitudinal mu ceiling (dry)
    downforce_coeff: float              # aerodynamic cornering gain, same units as AERO_LATERAL_GAIN
    drag_coeff: float                   # lumped CdA-like coefficient, same units as DRAG_COEFF
    aero_balance_front_pct: float       # front share of total downforce, 0-100
    max_brake_g: float                  # peak braking deceleration at full grip, dry
    battery_power_kw: float | None = None   # electric/hybrid boost, informational unless set
    class_name: str = "CUSTOM"

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Reference profile
# --------------------------------------------------------------------------
# The car implied by today's global assumptions, expressed as a CarProfile.
# A team car built from exactly this profile must reproduce the no-team-car
# simulation bit for bit -- that equivalence is asserted in
# tests/test_car_profiles.py and is what makes "team_car=None is identical to
# today" a checkable property rather than a claim.
REFERENCE_CAR_PROFILE = CarProfile(
    mass_kg=A.CAR_MASS,
    front_weight_pct=45.0,
    cg_height_m=0.30,
    power_kw=A.ENGINE_POWER / 1000.0,
    top_speed_kmh=A.MAX_CORNER_SPEED * 3.6 * 3.6,  # far above any corner-speed cap; never binds
    tyre_grip_coeff=A.LATERAL_MU,
    downforce_coeff=A.AERO_LATERAL_GAIN,
    drag_coeff=A.DRAG_COEFF,
    aero_balance_front_pct=40.0,
    max_brake_g=(A.BRAKE_MU + A.AERO_BRAKE_GAIN),  # peak mu+aero at the reference speed, ~4.95 g
    class_name="REFERENCE",
)

# --------------------------------------------------------------------------
# Illustrative class presets
# --------------------------------------------------------------------------
# Orderings (F1 fastest/heaviest-braking, Formula Student slowest) are
# plausible; exact figures are not manufacturer data and should not be
# presented as such.
CLASS_PRESETS: dict[str, CarProfile] = {
    "F1_2026": CarProfile(
        mass_kg=800.0, front_weight_pct=45.5, cg_height_m=0.28,
        power_kw=560.0, battery_power_kw=200.0, top_speed_kmh=350.0,
        tyre_grip_coeff=1.85, downforce_coeff=2.40, drag_coeff=1.05,
        aero_balance_front_pct=40.0, max_brake_g=4.95, class_name="F1_2026",
    ),
    "F2": CarProfile(
        mass_kg=755.0, front_weight_pct=45.0, cg_height_m=0.30,
        power_kw=390.0, top_speed_kmh=315.0,
        tyre_grip_coeff=1.65, downforce_coeff=1.70, drag_coeff=1.10,
        aero_balance_front_pct=38.0, max_brake_g=4.3, class_name="F2",
    ),
    "F3": CarProfile(
        mass_kg=660.0, front_weight_pct=45.0, cg_height_m=0.31,
        power_kw=280.0, top_speed_kmh=280.0,
        tyre_grip_coeff=1.50, downforce_coeff=1.20, drag_coeff=1.05,
        aero_balance_front_pct=38.0, max_brake_g=3.8, class_name="F3",
    ),
    "F4": CarProfile(
        mass_kg=645.0, front_weight_pct=46.0, cg_height_m=0.33,
        power_kw=119.0, top_speed_kmh=245.0,
        tyre_grip_coeff=1.30, downforce_coeff=0.55, drag_coeff=0.95,
        aero_balance_front_pct=40.0, max_brake_g=3.0, class_name="F4",
    ),
    "FORMULA_E": CarProfile(
        mass_kg=900.0, front_weight_pct=44.0, cg_height_m=0.32,
        power_kw=350.0, battery_power_kw=350.0, top_speed_kmh=322.0,
        tyre_grip_coeff=1.45, downforce_coeff=1.10, drag_coeff=1.00,
        aero_balance_front_pct=42.0, max_brake_g=3.6, class_name="FORMULA_E",
    ),
    "FORMULA_STUDENT": CarProfile(
        mass_kg=230.0, front_weight_pct=47.0, cg_height_m=0.29,
        power_kw=60.0, top_speed_kmh=130.0,
        tyre_grip_coeff=1.55, downforce_coeff=0.35, drag_coeff=0.80,
        aero_balance_front_pct=45.0, max_brake_g=2.4, class_name="FORMULA_STUDENT",
    ),
}


def preset_names() -> list[str]:
    return list(CLASS_PRESETS)


def from_preset(name: str) -> CarProfile:
    if name not in CLASS_PRESETS:
        raise KeyError(f"unknown car class preset '{name}'")
    p = CLASS_PRESETS[name]
    return CarProfile(**{**asdict(p)})


def car_profile_from_dict(d: dict) -> CarProfile:
    fields = {f for f in CarProfile.__dataclass_fields__}
    return CarProfile(**{k: v for k, v in d.items() if k in fields})


def catalogue() -> list[dict]:
    return [dict(id=name, **p.to_dict()) for name, p in CLASS_PRESETS.items()]
