"""Incident explanation.

Given a stored run, reconstruct *why* its worst conflict developed, from the
trajectory that led into it rather than from the outcome.

The explanation is built deterministically from structured simulation data. That
is a design decision, not a limitation: every clause in the generated narrative is
derived from a recorded number, so there is nothing for a language model to
invent. An optional LLM layer (``llm.py``) can rephrase the same structured chain
more fluently, but it is given only the chain and is explicitly forbidden from
adding facts — and the deterministic text remains available alongside it so the
two can be compared.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from . import assumptions as A
from .drivers import ARCHETYPES
from .safety import scsi_breakdown

ERROR_LABELS = {
    "missed_braking_point": "missed the braking point",
    "delayed_reaction": "reacted late",
    "unexpected_line_change": "changed line unexpectedly",
    "grip_loss": "lost grip briefly",
    "concentration_lapse": "had a momentary lapse in concentration",
    "over_aggressive_overtake": "committed more aggressively than usual",
    "incorrect_defensive_response": "defended the wrong side",
    "spin": "spun",
    "slow_response_to_car_ahead": "responded slowly to the car ahead",
}

DECISION_LABELS = {
    "accelerate": "was accelerating",
    "brake": "was braking",
    "coast": "was coasting",
    "maintain_line": "held its line",
    "move_left": "moved left",
    "move_right": "moved right",
    "initiate_overtake": "was committed to an overtake",
    "defend_inside": "was defending the inside line",
    "defend_outside": "was defending the outside line",
    "yield": "was conceding the position",
    "abort_overtake": "was abandoning its move",
    "avoid_collision": "was taking avoiding action",
    "return_to_racing_line": "was returning to the racing line",
}


def explain_run(store, run_id: str) -> dict:
    run = store.q1("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        return {}
    conflicts = store.q(
        "SELECT * FROM conflicts WHERE run_id=? ORDER BY min_ttc ASC", (run_id,))
    events = store.q(
        "SELECT * FROM events WHERE run_id=? ORDER BY t ASC", (run_id,))
    replay = store.get_replay(run_id)
    worst = conflicts[0] if conflicts else None

    root = _root_conditions(run, worst)
    chain = _event_chain(run, worst, events, replay)
    narrative = _narrative(run, worst, root, chain)
    return dict(
        run_id=run_id,
        conflict=worst,
        n_conflicts=len(conflicts),
        root_conditions=root,
        event_chain=chain,
        narrative=narrative,
        metrics=_metrics(worst),
        has_replay=bool(replay),
        caveat=(
            "This is a reconstruction of one simulated run under the assumptions "
            "listed in Model Assumptions. It describes what this model produced, "
            "not a real incident, and the surrogate measures quoted are not "
            "probabilities of a real-world crash."
        ),
    )


def _root_conditions(run: dict, worst: dict | None) -> list[dict]:
    out = [
        dict(group="Environment", label="Weather", value=run["weather"],
             detail="Preset condition; grip and visibility follow from it."),
        dict(group="Environment", label="Grip", value=round(run["grip"], 3),
             detail="Multiplier on both friction ceilings."),
        dict(group="Environment", label="Visibility", value=round(run["visibility"], 3),
             detail="Scales usable perception range."),
        dict(group="Environment", label="Spray", value=round(run["spray"], 3),
             detail="Extra perception penalty when following closely."),
        dict(group="Environment", label="Tyre condition",
             value=round(run["tyre_condition"], 3)),
        dict(group="Traffic", label="Cars on track", value=run["n_cars"]),
        dict(group="Traffic", label="Traffic density (measured)",
             value=round(run["traffic_density_measured"], 3),
             detail="Mean number of cars within 75 m, normalised. An output, not "
                    "an input."),
        dict(group="Traffic", label="Starting-gap spread",
             value=round(run["grid_spread"], 3)),
        dict(group="Track", label="Width multiplier",
             value=round(run["track_width_multiplier"], 3)),
        dict(group="Human error", label="Error-rate multiplier",
             value=round(run["error_rate_multiplier"], 3),
             detail="Scales every error rate in the assumptions registry."),
    ]
    if run["dominant_error"]:
        out.append(dict(group="Human error", label="Dominant error in this run",
                        value=run["dominant_error"]))
    if worst:
        for tag, arch in (("A", worst["archetype_a"]), ("B", worst["archetype_b"])):
            a = ARCHETYPES.get(arch)
            if not a:
                continue
            drv = worst["driver_a"] if tag == "A" else worst["driver_b"]
            out.append(dict(
                group=f"Driver {tag} ({drv})", label=a["label"], value=arch,
                detail=(f"aggression {a['aggression']:.2f}, "
                        f"risk tolerance {a['risk_tolerance']:.2f}, "
                        f"overtake willingness {a['overtake_willingness']:.2f}, "
                        f"defensive tendency {a['defensive_tendency']:.2f}, "
                        f"reaction {a['reaction_time']:.2f} s, "
                        f"late braking {a['late_braking_tendency']:.2f}"),
                traits={k: a[k] for k in (
                    "aggression", "risk_tolerance", "overtake_willingness",
                    "defensive_tendency", "reaction_time", "braking_consistency",
                    "late_braking_tendency", "line_change_tendency",
                    "predictability", "pace_multiplier")},
            ))
    return out


def _event_chain(run: dict, worst: dict | None, events: list[dict],
                 replay: dict | None) -> list[dict]:
    """Assemble an ordered causal chain from conditions, errors and trajectory."""
    chain: list[dict] = []

    def add(t, kind, actor, text, **metrics):
        chain.append(dict(t=None if t is None else round(float(t), 2), kind=kind,
                          actor=actor, text=text, metrics=metrics or None))

    # 1. Standing conditions
    weather_text = {
        "DRY": "Dry track.",
        "DAMP": "Damp track reduced available grip.",
        "WET": "Wet track reduced grip and visibility.",
        "HEAVY_RAIN": "Heavy rain sharply reduced grip and visibility, with heavy spray.",
    }.get(run["weather"], run["weather"])
    add(None, "condition", None,
        f"{weather_text} Grip {run['grip']:.2f}, visibility {run['visibility']:.2f}.",
        grip=round(run["grip"], 3), visibility=round(run["visibility"], 3))
    add(None, "condition", None,
        f"{run['n_cars']} cars on track at a measured traffic density of "
        f"{run['traffic_density_measured']:.2f}.",
        n_cars=run["n_cars"],
        traffic_density=round(run["traffic_density_measured"], 3))
    if run["grip"] < 0.9:
        stop_dry = (60.0 ** 2) / (2 * A.BRAKE_MU * 9.81)
        stop_now = (60.0 ** 2) / (2 * A.BRAKE_MU * 9.81 * run["grip"])
        add(None, "mechanism", None,
            f"At this grip level, braking from 60 m/s needs about "
            f"{stop_now - stop_dry:.0f} m more than in the dry.",
            extra_braking_distance_m=round(stop_now - stop_dry, 1))

    if not worst:
        return chain

    focus = {worst["driver_a_index"], worst["driver_b_index"]}
    t_min = worst["t_min_ttc"]

    # 2. Driver errors in the lead-in
    if replay:
        for e in replay.get("error_log", []):
            if e["driver_index"] in focus and e["t"] <= t_min + 0.5:
                who = (worst["driver_a"] if e["driver_index"] == worst["driver_a_index"]
                       else worst["driver_b"])
                add(e["t"], "error", who,
                    f"{who} {ERROR_LABELS.get(e['kind'], e['kind'])}.",
                    error=e["kind"])

    # 3. Racing intent, from the recorded event log
    for ev in events:
        if ev["t"] > t_min + 1.5:
            continue
        if ev["driver_a_index"] not in focus and ev["driver_b_index"] not in focus:
            continue
        detail = json.loads(ev["detail_json"] or "{}")
        et = ev["event_type"]
        if et == "overtake_aborted":
            add(ev["t"], "intent", ev["driver_a"],
                f"{ev['driver_a']} abandoned its move on {ev['driver_b']} "
                f"({detail.get('reason', 'safety')}).", **detail)
        elif et == "emergency_braking":
            add(ev["t"], "response", ev["driver_a"],
                f"{ev['driver_a']} braked at "
                f"{(ev['max_deceleration'] or 0) / 9.81:.1f} g.",
                deceleration=ev["max_deceleration"])
        elif et == "evasive_manoeuvre":
            add(ev["t"], "response", ev["driver_a"],
                f"{ev['driver_a']} made an evasive line change at "
                f"{abs(ev['lateral_rate'] or 0):.1f} m/s lateral.",
                lateral_rate=ev["lateral_rate"])
        elif et == "off_track":
            add(ev["t"], "outcome", ev["driver_a"],
                f"{ev['driver_a']} ran off track"
                + (" and reached the barrier." if detail.get("barrier_strike")
                   else f" with {detail.get('runoff_available', 0):.0f} m of runoff "
                        f"available."), **detail)
        elif et == "spin":
            add(ev["t"], "outcome", ev["driver_a"], f"{ev['driver_a']} spun.", **detail)

    # 4. The approach itself, read off the TTC trace
    if replay and replay.get("ttc_trace"):
        tr = replay["ttc_trace"]
        gaps = [p["gap"] for p in tr]
        closings = [p["closing_speed"] for p in tr]
        i_peak = int(np.argmax(closings)) if closings else 0
        add(tr[i_peak]["t"], "approach", worst["driver_a"],
            f"Closing speed peaked at {closings[i_peak]:.1f} m/s with "
            f"{gaps[i_peak]:.0f} m between them.",
            closing_speed=round(closings[i_peak], 2), gap=round(gaps[i_peak], 1))
        with_ttc = [p for p in tr if p["ttc"] is not None]
        if with_ttc:
            first = with_ttc[0]
            add(first["t"], "approach", None,
                f"Trajectories first projected to intersect: TTC "
                f"{first['ttc']:.2f} s.", ttc=first["ttc"])

    # 5. What each driver was doing at the critical instant
    da = DECISION_LABELS.get(worst["a_decision"], worst["a_decision"])
    db = DECISION_LABELS.get(worst["b_decision"], worst["b_decision"])
    if da or db:
        add(t_min, "state", None,
            f"At minimum TTC, {worst['driver_a']} {da} and "
            f"{worst['driver_b']} {db}.",
            a_decision=worst["a_decision"], b_decision=worst["b_decision"])

    # 6. The measured minimum
    add(t_min, "critical", None,
        f"Minimum TTC {worst['min_ttc']:.2f} s"
        + (f", minimum PET {worst['min_pet']:.2f} s" if worst["min_pet"] is not None
           else "")
        + f", closing speed {worst['closing_speed']:.1f} m/s, peak deceleration "
          f"{worst['max_deceleration'] / 9.81:.1f} g, in the "
          f"{worst['location']}.",
        min_ttc=worst["min_ttc"], min_pet=worst["min_pet"],
        closing_speed=worst["closing_speed"],
        max_deceleration=worst["max_deceleration"])

    # 7. Resolution
    if worst["collision"]:
        add(t_min, "outcome", None, "The interaction ended in contact.")
    elif worst["evasive_action"]:
        add(t_min, "outcome", None,
            "The interaction was resolved by evasive action without contact — "
            "a near miss in this model's terms.")
    else:
        add(t_min, "outcome", None, "The interaction resolved without contact.")

    chain.sort(key=lambda c: (c["t"] is not None, c["t"] if c["t"] is not None else 0))
    return chain


def _metrics(worst: dict | None) -> dict:
    if not worst:
        return {}
    return dict(
        min_ttc=worst["min_ttc"],
        min_pet=worst["min_pet"],
        closing_speed=worst["closing_speed"],
        closing_speed_kph=round((worst["closing_speed"] or 0) * 3.6, 1),
        max_deceleration=worst["max_deceleration"],
        max_deceleration_g=round((worst["max_deceleration"] or 0) / 9.81, 2),
        evasive_action=bool(worst["evasive_action"]),
        collision=bool(worst["collision"]),
        conflict_type=worst["conflict_type"],
        severity=worst["severity"],
        scsi=worst["scsi"],
        scsi_breakdown=scsi_breakdown(
            worst["min_ttc"], worst["min_pet"], worst["closing_speed"] or 0.0,
            worst["max_deceleration"] or 0.0),
        thresholds=dict(
            ttc_conflict=A.TTC_CONFLICT_THRESHOLD,
            ttc_critical=A.TTC_CRITICAL_THRESHOLD,
            pet_conflict=A.PET_CONFLICT_THRESHOLD,
            pet_critical=A.PET_CRITICAL_THRESHOLD,
        ),
    )


def _narrative(run: dict, worst: dict | None, root: list[dict],
               chain: list[dict]) -> str:
    """Prose assembled from the chain. Every clause traces to a recorded number."""
    if not worst:
        return ("This run produced no interaction that crossed the surrogate-safety "
                "filter.")
    a, b = worst["driver_a"], worst["driver_b"]
    arch_a = ARCHETYPES.get(worst["archetype_a"], {}).get(
        "label", worst["archetype_a"])
    arch_b = ARCHETYPES.get(worst["archetype_b"], {}).get(
        "label", worst["archetype_b"])
    parts: list[str] = []

    cond = f"{run['weather'].replace('_', ' ').lower()} conditions"
    parts.append(
        f"In {cond} (grip {run['grip']:.2f}, visibility {run['visibility']:.2f}) with "
        f"{run['n_cars']} cars on track at a measured density of "
        f"{run['traffic_density_measured']:.2f}, {a} "
        f"({arch_a} profile) and {b} ({arch_b} profile) converged in the "
        f"{worst['location']}."
    )

    errs = [c for c in chain if c["kind"] == "error"]
    if errs:
        parts.append(
            " " + " ".join(e["text"] for e in errs[:3])
        )

    approach = [c for c in chain if c["kind"] == "approach"]
    if approach:
        parts.append(" " + " ".join(c["text"] for c in approach))

    state = next((c for c in chain if c["kind"] == "state"), None)
    if state:
        parts.append(" " + state["text"])

    pet_txt = (f" and a minimum post-encroachment time of {worst['min_pet']:.2f} s"
               if worst["min_pet"] is not None else "")
    parts.append(
        f" The interaction reached a minimum time-to-collision of "
        f"{worst['min_ttc']:.2f} s{pet_txt}, with a peak deceleration of "
        f"{worst['max_deceleration'] / 9.81:.1f} g."
    )

    if worst["collision"]:
        parts.append(" Contact occurred.")
    elif worst["evasive_action"]:
        parts.append(" Evasive action resolved it without contact.")
    else:
        parts.append(" It resolved without contact or evasive action.")

    parts.append(
        f" Classified {worst['severity']} / {worst['conflict_type']} by the "
        f"thresholds in Model Assumptions. This is one simulated run; it is not "
        f"evidence about real-world crash likelihood."
    )
    return "".join(parts)


def explain_hotspot(store, batch_id: str, segment_index: int) -> dict:
    """Plain-language answer to "why is this location flagged?", from the data."""
    from .analysis import hotspot_detail
    detail = hotspot_detail(store, batch_id, segment_index)
    if not detail:
        return {}
    seg = detail["segment"]
    n_runs = detail["n_runs"]

    lines = []
    lines.append(
        f"{seg['name']} accounted for {seg['conflicts']} conflicts across "
        f"{n_runs} simulated runs ({seg['conflicts_per_run']:.3f} per run), of "
        f"which {seg['critical']} were classified critical and "
        f"{seg['collisions']} involved contact."
    )
    if seg["median_min_ttc"] is not None:
        lines.append(
            f"Median minimum TTC there was {seg['median_min_ttc']:.2f} s "
            f"(5th percentile {seg['p05_min_ttc']:.2f} s)"
            + (f", median PET {seg['median_min_pet']:.2f} s."
               if seg["median_min_pet"] is not None else ".")
        )
    note = detail["geometry_note"].rstrip()
    lines.append(f"Geometry: {note}{'' if note.endswith('.') else '.'}")

    mix = seg["conflict_type_mix"]
    if mix:
        top = sorted(mix.items(), key=lambda kv: -kv[1])[:2]
        lines.append(
            "Most common interaction: "
            + ", ".join(f"{k.replace('_', ' ').lower()} ({v})" for k, v in top) + "."
        )

    wc = sorted(detail["weather_contrast"], key=lambda w: -w["conflicts_per_run"])
    if wc:
        lines.append(
            "By condition, conflicts per run here were "
            + ", ".join(f"{w['band']} {w['conflicts_per_run']:.3f}" for w in wc) + "."
        )
    dc = sorted(detail["density_contrast"], key=lambda w: -w["conflicts_per_run"])
    if dc:
        lines.append(
            "By traffic density band, "
            + ", ".join(f"{w['band']} {w['conflicts_per_run']:.3f}" for w in dc) + "."
        )
    lines.append(
        "These are counts of conflicts detected in simulated trajectories under "
        "this batch's assumptions. They are not real-world incident rates, and "
        "they do not establish that this corner is unsafe."
    )
    return dict(segment_index=segment_index, text=" ".join(lines), detail=detail)
