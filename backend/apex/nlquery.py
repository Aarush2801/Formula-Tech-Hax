"""Ask the Simulator: natural-language questions over stored simulation results.

Implemented as a rule-based intent router rather than a text-to-SQL model, for one
reason: every answer must be traceable. Each intent maps to a fixed, reviewed SQL
query, and the response carries the query and the rows it returned alongside the
prose. A reader can check the answer.

An optional LLM layer may rephrase the resulting structured answer (see
``llm.py``), but the numbers always come from these queries, and the deterministic
answer is always returned too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .drivers import ARCHETYPES

SUGGESTIONS = [
    "Show me the most dangerous scenarios in wet conditions",
    "Which driver interactions produce the lowest TTC?",
    "Does traffic density matter more than aggression?",
    "Show me all incidents involving three or more cars",
    "Why is Turn 7 a hotspot?",
    "Compare wet and dry conditions",
    "Which corner has the most critical conflicts?",
    "What happens when grip is reduced?",
    "How often did contact occur?",
    "Which human error appears most in critical runs?",
]


@dataclass
class Intent:
    name: str
    patterns: list[str]
    handler: Callable
    description: str


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


# --------------------------------------------------------------------------
# Handlers. Each returns (text, data, queries)
# --------------------------------------------------------------------------
def _h_worst_in_condition(store, batch_id, q, m):
    weather = _weather_from(q) or "WET"
    sql = """SELECT c.run_id, c.location, c.turn_number, c.conflict_type, c.severity,
                    c.min_ttc, c.min_pet, c.closing_speed, c.max_deceleration,
                    c.archetype_a, c.archetype_b, c.collision, c.evasive_action,
                    c.scsi, r.n_cars, r.traffic_density_measured, r.grip,
                    r.has_replay
             FROM conflicts c JOIN runs r ON r.id=c.run_id
             WHERE c.batch_id=? AND c.weather=?
             ORDER BY c.min_ttc ASC, c.scsi DESC LIMIT 12"""
    rows = store.q(sql, (batch_id, weather))
    if not rows:
        return (f"No conflicts were recorded in {weather} conditions in this batch.",
                dict(rows=[]), [dict(sql=sql, params=[batch_id, weather])])
    top = rows[0]
    text = (
        f"In {weather.replace('_', ' ').lower()} conditions this batch's most severe "
        f"simulated interactions were concentrated in the "
        f"{top['location']}. The single lowest minimum TTC was "
        f"{top['min_ttc']:.2f} s, between a "
        f"{_lab(top['archetype_a'])} and a {_lab(top['archetype_b'])} profile, "
        f"classified {top['conflict_type'].replace('_', ' ').lower()}, with a "
        f"closing speed of {top['closing_speed']:.1f} m/s and peak deceleration of "
        f"{top['max_deceleration'] / 9.81:.1f} g. "
        f"{sum(1 for r in rows if r['collision'])} of these top 12 ended in contact."
    )
    return text, dict(rows=rows, weather=weather), [dict(sql=sql, params=[batch_id, weather])]


def _h_lowest_ttc_pairs(store, batch_id, q, m):
    sql = """SELECT archetype_a, archetype_b, COUNT(*) n,
                    ROUND(AVG(min_ttc),4) mean_min_ttc,
                    ROUND(MIN(min_ttc),4) lowest_min_ttc,
                    SUM(collision) collisions
             FROM conflicts WHERE batch_id=? AND severity IN ('CRITICAL','INCIDENT')
             GROUP BY archetype_a, archetype_b HAVING n >= 5
             ORDER BY mean_min_ttc ASC LIMIT 12"""
    rows = store.q(sql, (batch_id,))
    if not rows:
        return ("Not enough critical conflicts in this batch to rank behavioural "
                "pairings.", dict(rows=[]), [dict(sql=sql, params=[batch_id])])
    t = rows[0]
    text = (
        f"Ranked by mean minimum TTC across critical conflicts, the lowest-TTC "
        f"pairing in this batch was {_lab(t['archetype_a'])} against "
        f"{_lab(t['archetype_b'])}: mean {t['mean_min_ttc']:.2f} s over "
        f"{t['n']} conflicts, lowest {t['lowest_min_ttc']:.2f} s. "
        f"Note these are raw counts by pairing, not normalised for how often each "
        f"profile was sampled — the Driver Analysis matrix normalises by "
        f"co-presence, and is the fairer comparison."
    )
    return text, dict(rows=rows), [dict(sql=sql, params=[batch_id])]


def _h_compare_parameters(store, batch_id, q, m):
    from .analysis import sensitivity
    sens = sensitivity(store, batch_id)
    params = sens.get("parameters", [])
    if not params:
        return ("This batch has too few runs for a sensitivity comparison.",
                dict(), [])
    named = []
    for want, label in (("traffic", "traffic_density_measured"),
                        ("aggress", "trait_aggression"),
                        ("grip", "grip"),
                        ("reaction", "trait_reaction_time"),
                        ("width", "track_width_multiplier"),
                        ("error", "error_rate_multiplier"),
                        ("visib", "visibility")):
        if want in q:
            named.append(label)
    subset = [p for p in params if p["key"] in named] if named else params[:4]
    ranked = sorted(subset, key=lambda p: -abs(p["correlations"].get("n_critical", 0)))
    bits = [
        f"{p['label']} (rho = {p['correlations'].get('n_critical', 0):+.3f})"
        for p in ranked
    ]
    text = (
        "Ranked by Spearman rank correlation with critical conflicts per run in "
        "this batch: " + "; ".join(bits) + ". "
        + (f"{ranked[0]['label']} shows the strongest association. " if ranked else "")
        + "These are associations within the model. The sampler draws these "
          "parameters independently, so they are not confounded with each other "
          "here, but the result describes the simulation, not racing."
    )
    return text, dict(parameters=ranked), [dict(sql="see /api/analysis/sensitivity",
                                                params=[batch_id])]


def _h_multi_car(store, batch_id, q, m):
    n = 3
    mm = re.search(r"(\d+)\s*or more", q) or re.search(r"(\d+)\+", q)
    if mm:
        n = int(mm.group(1))
    # A multi-car involvement means one run where at least n distinct drivers
    # appear across its conflict records.
    sql = """SELECT run_id, COUNT(DISTINCT driver_a || '/' || driver_b) pairs,
                    COUNT(*) conflicts, MIN(min_ttc) lowest_ttc,
                    SUM(collision) collisions, GROUP_CONCAT(DISTINCT location) locations
             FROM conflicts WHERE batch_id=?
             GROUP BY run_id
             HAVING COUNT(*) >= ?
             ORDER BY collisions DESC, lowest_ttc ASC LIMIT 15"""
    rows = store.q(sql, (batch_id, max(n - 1, 2)))
    drv_sql = """SELECT run_id, driver_a, driver_b FROM conflicts WHERE batch_id=?"""
    allc = store.q(drv_sql, (batch_id,))
    involved: dict[str, set] = {}
    for c in allc:
        involved.setdefault(c["run_id"], set()).update([c["driver_a"], c["driver_b"]])
    multi = [dict(run_id=k, drivers=sorted(v), n_drivers=len(v))
             for k, v in involved.items() if len(v) >= n]
    multi.sort(key=lambda r: -r["n_drivers"])
    text = (
        f"{len(multi)} of this batch's runs produced conflicts involving "
        f"{n} or more distinct cars. The largest involved "
        f"{multi[0]['n_drivers']} cars." if multi else
        f"No run in this batch produced conflicts involving {n} or more distinct cars."
    )
    return text, dict(runs=multi[:20], chains=rows), [
        dict(sql=sql, params=[batch_id, max(n - 1, 2)])]


def _h_hotspot_why(store, batch_id, q, m):
    from .explain import explain_hotspot
    from .analysis import hotspots
    turn = None
    mm = re.search(r"turn\s*(\d+)", q)
    if mm:
        turn = int(mm.group(1))
    hs = hotspots(store, batch_id)
    if turn is not None:
        cands = [s for s in hs["segments"] if s["turn_number"] == turn]
        seg = max(cands, key=lambda s: s["conflicts"]) if cands else None
    else:
        seg = hs["top_segments"][0] if hs["top_segments"] else None
    if not seg:
        return ("No conflicts were recorded at that location in this batch.",
                dict(), [])
    ex = explain_hotspot(store, batch_id, seg["segment_index"])
    return ex["text"], dict(segment=seg, detail=ex.get("detail")), [
        dict(sql="see /api/analysis/hotspots", params=[batch_id])]


def _h_compare_weather(store, batch_id, q, m):
    from .analysis import environment_analysis
    env = environment_analysis(store, batch_id)
    rows = env["by_weather"]
    if not rows:
        return ("This batch has no runs to compare.", dict(), [])
    bits = []
    for r in rows:
        bits.append(
            f"{r['weather'].replace('_', ' ').lower()}: "
            f"{r['conflicts_per_run']:.2f} conflicts/run, "
            f"{r['critical_per_run']:.2f} critical/run, "
            f"{r['collisions_per_run']:.2f} contacts/run, "
            f"{r['off_track_per_run']:.2f} excursions/run, "
            f"mean minimum TTC {r['mean_min_ttc']:.2f} s"
        )
    dry = next((r for r in rows if r["weather"] == "DRY"), None)
    wet = next((r for r in rows if r["weather"] in ("WET", "HEAVY_RAIN")), None)
    tail = ""
    if dry and wet:
        if wet["conflicts_per_run"] < dry["conflicts_per_run"] and \
           wet["mean_min_ttc"] < dry["mean_min_ttc"]:
            tail = (" In this batch the wetter conditions produced *fewer but more "
                    "severe* conflicts, alongside markedly more off-track "
                    "excursions — speeds and speed differentials fall, so fewer "
                    "overtakes are attempted, but the ones that develop leave less "
                    "margin.")
    return ("Per simulated run, by condition — " + "; ".join(bits) + "." + tail +
            " All figures are per-run counts within this batch's window length.",
            dict(by_weather=rows), [dict(sql="see /api/analysis/environment",
                                         params=[batch_id])])


def _h_top_corner(store, batch_id, q, m):
    sql = """SELECT location, turn_number, COUNT(*) conflicts,
                    SUM(CASE WHEN severity='CRITICAL' THEN 1 ELSE 0 END) critical,
                    SUM(collision) collisions, ROUND(AVG(min_ttc),4) mean_ttc,
                    ROUND(MIN(min_ttc),4) lowest_ttc
             FROM conflicts WHERE batch_id=?
             GROUP BY segment_index ORDER BY critical DESC, conflicts DESC LIMIT 10"""
    rows = store.q(sql, (batch_id,))
    if not rows:
        return ("No conflicts recorded in this batch.", dict(rows=[]), [])
    t = rows[0]
    text = (
        f"By critical-conflict count, the {t['location']} led this batch with "
        f"{t['critical']} critical conflicts out of {t['conflicts']} total, mean "
        f"minimum TTC {t['mean_ttc']:.2f} s and lowest {t['lowest_ttc']:.2f} s. "
        f"This is a simulated conflict count under this batch's assumptions, not a "
        f"statement that the corner is unsafe."
    )
    return text, dict(rows=rows), [dict(sql=sql, params=[batch_id])]


def _h_grip_effect(store, batch_id, q, m):
    sql = """SELECT ROUND(grip,1) grip_band, COUNT(*) runs,
                    ROUND(AVG(n_conflicts),3) conflicts_per_run,
                    ROUND(AVG(n_critical),3) critical_per_run,
                    ROUND(AVG(n_collisions),3) collisions_per_run,
                    ROUND(AVG(n_off_track),3) off_track_per_run,
                    ROUND(AVG(min_ttc),4) mean_min_ttc
             FROM runs WHERE batch_id=? GROUP BY grip_band ORDER BY grip_band"""
    rows = store.q(sql, (batch_id,))
    if not rows:
        return ("No runs in this batch.", dict(rows=[]), [])
    lo, hi = rows[0], rows[-1]
    text = (
        f"Across grip bands from {lo['grip_band']} to {hi['grip_band']}: conflicts "
        f"per run went {lo['conflicts_per_run']:.2f} -> {hi['conflicts_per_run']:.2f}, "
        f"off-track excursions {lo['off_track_per_run']:.2f} -> "
        f"{hi['off_track_per_run']:.2f}, and mean minimum TTC "
        f"{lo['mean_min_ttc']:.2f} s -> {hi['mean_min_ttc']:.2f} s. "
        f"In this model, reduced grip shows up far more strongly in excursions and "
        f"in conflict severity than in conflict counts."
    )
    return text, dict(rows=rows), [dict(sql=sql, params=[batch_id])]


def _h_contact_rate(store, batch_id, q, m):
    sql = """SELECT COUNT(*) runs, SUM(n_collisions) collisions,
                    SUM(n_light_contacts) light_contacts,
                    SUM(CASE WHEN n_collisions>0 THEN 1 ELSE 0 END) runs_with_collision,
                    SUM(n_off_track) off_track, SUM(n_spins) spins
             FROM runs WHERE batch_id=?"""
    r = store.q1(sql, (batch_id,))
    text = (
        f"Across {r['runs']} simulated runs this batch recorded "
        f"{r['collisions']} collisions and {r['light_contacts']} light "
        f"(wheel-to-wheel) contacts, with at least one collision in "
        f"{r['runs_with_collision']} runs "
        f"({_pct(r['runs_with_collision'] / max(r['runs'], 1))} of runs). There were "
        f"also {r['off_track']} off-track excursions and {r['spins']} spins. "
        f"These are simulated outcomes under this batch's assumptions and are not "
        f"real-world crash frequencies."
    )
    return text, dict(totals=r), [dict(sql=sql, params=[batch_id])]


def _h_error_in_critical(store, batch_id, q, m):
    sql = """SELECT dominant_error, COUNT(*) runs,
                    ROUND(AVG(n_critical),3) critical_per_run,
                    ROUND(AVG(n_collisions),3) collisions_per_run,
                    ROUND(AVG(min_ttc),4) mean_min_ttc
             FROM runs WHERE batch_id=? AND n_critical>0
             GROUP BY dominant_error ORDER BY runs DESC LIMIT 10"""
    rows = store.q(sql, (batch_id,))
    if not rows:
        return ("No runs with critical conflicts in this batch.", dict(rows=[]), [])
    t = rows[0]
    text = (
        f"Among runs that produced at least one critical conflict, the most common "
        f"dominant human-error event was "
        f"{(t['dominant_error'] or 'none').replace('_', ' ')} "
        f"({t['runs']} runs, {t['critical_per_run']:.2f} critical conflicts per run). "
        f"Error rates are configurable assumptions, not measured incident rates — "
        f"the 'dominant' error is simply the most frequent non-grip-loss event in "
        f"that run."
    )
    return text, dict(rows=rows), [dict(sql=sql, params=[batch_id])]


def _h_patterns(store, batch_id, q, m):
    sql = """SELECT rank, location, weather, traffic_band, conflict_type, occurrences,
                    runs_evaluated, median_min_ttc, median_min_pet, evasive_rate,
                    collision_rate, archetype_a, archetype_b
             FROM patterns WHERE batch_id=? ORDER BY rank LIMIT 10"""
    rows = store.q(sql, (batch_id,))
    if not rows:
        return ("No recurring patterns have been computed for this batch yet.",
                dict(rows=[]), [])
    t = rows[0]
    text = (
        f"The most frequently recurring critical pattern in this batch was "
        f"{t['location']} in {t['weather'].replace('_', ' ').lower()} conditions at "
        f"{t['traffic_band'].lower()} traffic density, typed "
        f"{t['conflict_type'].replace('_', ' ').lower()}. It produced qualifying "
        f"conflicts in {t['occurrences']} of {t['runs_evaluated']} simulated runs, "
        f"with a median minimum TTC of {t['median_min_ttc']:.2f} s and evasive "
        f"action in {_pct(t['evasive_rate'])} of instances. That is a simulated "
        f"recurrence count, not a real-world probability."
    )
    return text, dict(rows=rows), [dict(sql=sql, params=[batch_id])]


def _h_fallback(store, batch_id, q, m):
    from .analysis import overview
    ov = overview(store, batch_id)
    tot = ov.get("totals", {})
    text = (
        f"I can answer questions about locations, conditions, behavioural pairings, "
        f"parameter sensitivity, recurring patterns and outcome counts in this "
        f"batch. This batch has {tot.get('runs', 0)} runs, "
        f"{tot.get('conflicts', 0)} conflicts ({tot.get('critical', 0)} critical) "
        f"and {tot.get('collisions', 0)} collisions. Try one of the suggested "
        f"questions."
    )
    return text, dict(overview=tot, suggestions=SUGGESTIONS), []


INTENTS: list[Intent] = [
    Intent("worst_in_condition",
           [r"most dangerous", r"worst.*(wet|dry|damp|rain)", r"severe.*(wet|dry|rain)",
            r"(wet|heavy rain|damp).*(dangerous|worst|severe)"],
           _h_worst_in_condition,
           "Most severe conflicts in a given weather condition"),
    Intent("compare_weather",
           [r"compare.*(wet|dry|weather|condition)", r"(wet|dry).*(versus|vs|and dry|and wet)",
            r"effect of (weather|rain)"],
           _h_compare_weather, "Compare outcomes across weather conditions"),
    Intent("lowest_ttc_pairs",
           [r"(driver|behaviour|behavior|profile|archetype).*(interaction|pair|combination)",
            r"lowest ttc", r"which.*interactions"],
           _h_lowest_ttc_pairs, "Behavioural pairings ranked by TTC"),
    Intent("compare_parameters",
           [r"matter more", r"more important", r"which parameter", r"sensitivity",
            r"strongest", r"(traffic|density).*(versus|vs|than).*(aggress)",
            r"what (actually )?drives"],
           _h_compare_parameters, "Rank parameters by association with conflicts"),
    Intent("multi_car",
           [r"three or more", r"3 or more", r"\d\+ cars", r"multi[- ]car", r"chain"],
           _h_multi_car, "Runs with multi-car involvement"),
    Intent("hotspot_why",
           [r"why is turn", r"why.*hotspot", r"why.*flagged", r"why.*turn \d"],
           _h_hotspot_why, "Why a location is flagged"),
    Intent("top_corner",
           [r"which corner", r"which turn", r"most critical", r"worst corner",
            r"most conflicts"],
           _h_top_corner, "Corner ranked by critical conflicts"),
    Intent("grip_effect",
           [r"grip", r"reduced grip", r"less grip"], _h_grip_effect,
           "Effect of grip on outcomes"),
    Intent("contact_rate",
           [r"how often.*(contact|collision|crash)", r"how many.*(collision|contact)",
            r"collision rate"],
           _h_contact_rate, "Contact and incident counts"),
    Intent("error_in_critical",
           [r"(human )?error", r"mistake", r"late braking.*critical"],
           _h_error_in_critical, "Human error in critical runs"),
    Intent("patterns",
           [r"recurring", r"pattern", r"top scenario", r"keeps? (happening|appearing)"],
           _h_patterns, "Top recurring patterns"),
]


def _weather_from(q: str) -> str | None:
    if "heavy rain" in q or "heavy_rain" in q:
        return "HEAVY_RAIN"
    for w in ("wet", "damp", "dry"):
        if re.search(rf"\b{w}\b", q):
            return w.upper()
    return None


def _lab(arch: str | None) -> str:
    return ARCHETYPES.get(arch or "", {}).get("label", arch or "unknown")


def ask(store, batch_id: str, question: str) -> dict:
    q = (question or "").strip().lower()
    matched: Intent | None = None
    for intent in INTENTS:
        for pat in intent.patterns:
            if re.search(pat, q):
                matched = intent
                break
        if matched:
            break

    handler = matched.handler if matched else _h_fallback
    name = matched.name if matched else "fallback"
    try:
        text, data, queries = handler(store, batch_id, q, None)
    except Exception as exc:  # a failed query must not look like an answer
        return dict(
            question=question, intent=name, answer=None,
            error=f"{type(exc).__name__}: {exc}",
            note="The query failed; no answer is being reported.",
        )
    return dict(
        question=question,
        intent=name,
        intent_description=matched.description if matched else
        "No specific intent matched; returned a batch summary.",
        answer=text,
        data=data,
        queries=queries,
        suggestions=SUGGESTIONS,
        provenance=(
            "Answer generated from fixed SQL queries against this batch's stored "
            "simulation results. The queries used are included above so the answer "
            "can be checked. No figure here is a real-world statistic."
        ),
    )
