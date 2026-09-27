from apex import assumptions as A
from apex.wear import estimated_repair_cost, wear_for_race, wear_from_contact, wear_from_kerb_strike


def test_kerb_wear_is_nonlinear_in_severity():
    """'Harder hits add much more wear' means the ratio grows faster than the
    severity ratio, not just proportionally."""
    soft = sum(wear_from_kerb_strike(dict(severity=0.2, lateral_offset=0.5)).values())
    hard = sum(wear_from_kerb_strike(dict(severity=0.9, lateral_offset=0.5)).values())
    severity_ratio = 0.9 / 0.2
    wear_ratio = hard / soft
    assert wear_ratio > severity_ratio


def test_kerb_wear_attributes_left_and_right_correctly():
    left = wear_from_kerb_strike(dict(severity=0.5, lateral_offset=1.2))
    right = wear_from_kerb_strike(dict(severity=0.5, lateral_offset=-1.2))
    assert left["suspension_fl"] > 0 and left["suspension_rl"] > 0
    assert left.get("suspension_fr", 0) == 0 and left.get("suspension_rr", 0) == 0
    assert right["suspension_fr"] > 0 and right["suspension_rr"] > 0
    assert right.get("suspension_fl", 0) == 0


def test_kerb_wear_includes_wheel_share():
    w = wear_from_kerb_strike(dict(severity=0.6, lateral_offset=1.0))
    assert w["wheels"] > 0


def test_contact_wear_severe_multiplier_applied():
    light = wear_from_contact(dict(impact_speed=8.0, severe=False, side="left"))
    severe = wear_from_contact(dict(impact_speed=8.0, severe=True, side="left"))
    total_light = sum(light.values())
    total_severe = sum(severe.values())
    assert total_severe == total_light * A.CONTACT_WEAR_SEVERE_MULTIPLIER


def test_contact_wear_covers_suspension_wheels_and_brakes():
    w = wear_from_contact(dict(impact_speed=10.0, severe=True, side="right"))
    assert set(w) == {"suspension_fr", "suspension_rr", "wheels", "brakes"}
    assert all(v > 0 for v in w.values())


def test_wear_for_race_empty_telemetry_is_all_zero():
    totals = wear_for_race(None)
    assert set(totals) == set(A.PASSPORT_PARTS)
    assert all(v == 0.0 for v in totals.values())


def test_wear_for_race_aggregates_multiple_events():
    telemetry = dict(
        kerb_strikes=[dict(severity=0.3, lateral_offset=1.0),
                     dict(severity=0.7, lateral_offset=1.0)],
        contacts=[dict(impact_speed=5.0, severe=False, side="right")],
    )
    totals = wear_for_race(telemetry)
    assert totals["suspension_fl"] > 0  # from both kerb strikes (left side)
    assert totals["suspension_fr"] > 0  # from the contact (right side)
    assert totals["wheels"] > 0
    assert totals["brakes"] > 0


def test_estimated_repair_cost_zero_with_no_contacts():
    assert estimated_repair_cost(dict(contacts=[])) == 0.0
    assert estimated_repair_cost(None) == 0.0


def test_estimated_repair_cost_uses_severe_vs_light_pricing():
    light_only = estimated_repair_cost(dict(contacts=[dict(severe=False)]))
    severe_only = estimated_repair_cost(dict(contacts=[dict(severe=True)]))
    assert light_only == A.CONTACT_REPAIR_COST_LIGHT
    assert severe_only == A.CONTACT_REPAIR_COST_SEVERE
    assert severe_only > light_only
