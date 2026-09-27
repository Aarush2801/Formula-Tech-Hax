"""Automated circuit safety stress-test report.

Assembled entirely from stored analyses. The structure mirrors how the
methodology would be written up: what was configured, what the model assumes,
what the surrogate measures showed, and — at the same length as the results — what
the study cannot support.

The limitations section is not boilerplate. It is generated from the actual
configuration, so it names the specific assumptions that drove the specific
numbers above it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from . import assumptions as A
from .circuits import get_track
from .drivers import ARCHETYPES


def _fmt(x, nd=3, dash="—"):
    if x is None:
        return dash
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def generate_report(store, batch_id: str, *, track_id: str = "vale_park") -> dict:
    from .analysis import (conflict_breakdown, environment_analysis, hotspots,
                           interaction_matrix, overview, sensitivity)

    ov = store.get_analysis(batch_id, "overview") or overview(store, batch_id)
    hs = store.get_analysis(batch_id, "hotspots") or hotspots(store, batch_id, track_id)
    sens = store.get_analysis(batch_id, "sensitivity") or sensitivity(store, batch_id)
    im = store.get_analysis(batch_id, "interaction_matrix") or \
        interaction_matrix(store, batch_id)
    env = store.get_analysis(batch_id, "environment") or \
        environment_analysis(store, batch_id)
    cb = store.get_analysis(batch_id, "conflict_breakdown") or \
        conflict_breakdown(store, batch_id)
    patterns = store.q(
        "SELECT * FROM patterns WHERE batch_id=? ORDER BY rank LIMIT 20", (batch_id,))
    track = get_track(track_id)
    tot = ov.get("totals", {})
    n_runs = tot.get("runs") or 0

    S: list[str] = []
    A_ = S.append

    A_(f"# Circuit Safety Stress-Test Report")
    A_("")
    A_(f"**Circuit** {track.name} ({track.length:.0f} m, {len(track.corners)} corners)  ")
    A_(f"**Batch** `{batch_id}` — {ov.get('label', '')}  ")
    A_(f"**Mode** {ov.get('mode')}  ")
    A_(f"**Runs** {n_runs:,}  ")
    A_(f"**Generated** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    A_("")
    A_("> This report describes the behaviour of a simulation model. Every count and "
       "rate below is an output of that model under the assumptions listed in "
       "section 4. None of them is a real-world crash frequency, probability or "
       "safety assessment, and none of them should be read as an evaluation of a "
       "real circuit, driver or series.")
    A_("")

    # ---- 1. Executive summary ---------------------------------------------
    A_("## 1. Executive summary")
    A_("")
    A_(f"{n_runs:,} simulations were generated and executed, each a "
       f"{A.SIM_DURATION:.0f}-second racing window on {track.name} with a "
       f"multi-agent field. Across those runs the surrogate-safety analyser "
       f"detected **{tot.get('conflicts', 0):,} conflicts**, of which "
       f"**{tot.get('critical', 0):,} were classified critical**. "
       f"**{tot.get('near_misses', 0):,} were near misses** (evasive action taken, no "
       f"contact), and **{tot.get('collisions', 0):,} involved contact above the "
       f"collision energy threshold**, with a further "
       f"{tot.get('light_contacts', 0):,} light wheel-to-wheel contacts. "
       f"There were {tot.get('off_track', 0):,} off-track excursions and "
       f"{tot.get('spins', 0):,} spins.")
    A_("")
    if tot.get("avg_min_ttc") is not None:
        A_(f"Mean minimum time-to-collision across runs that produced a conflict was "
           f"{_fmt(tot.get('avg_min_ttc'))} s, with the lowest single value at "
           f"{_fmt(tot.get('lowest_min_ttc'))} s. At least one critical conflict "
           f"occurred in {ov.get('fraction_runs_with_critical', 0) * 100:.1f}% of runs.")
        A_("")
    if hs.get("top_segments"):
        t = hs["top_segments"][0]
        A_(f"The most frequently flagged location was the **{t['name']}** "
           f"({t['conflicts']} conflicts, {t['conflicts_per_run']:.3f} per run, median "
           f"minimum TTC {_fmt(t['median_min_ttc'], 2)} s).")
        A_("")
    if sens.get("parameters"):
        p = sens["parameters"][0]
        A_(f"Of the parameters searched, **{p['label']}** showed the strongest "
           f"association with critical conflict frequency "
           f"(Spearman rho = {p['correlations'].get('n_critical', 0):+.3f}).")
        A_("")

    # ---- 2. Simulation configuration --------------------------------------
    A_("## 2. Simulation configuration")
    A_("")
    space = ov.get("space") or {}
    A_(_table(["Setting", "Value"], [
        ["Runs", f"{n_runs:,}"],
        ["Seed base", ov.get("seed_base")],
        ["Timestep", f"{A.DT} s ({1 / A.DT:.0f} Hz)"],
        ["Window per run", f"{A.SIM_DURATION:.0f} s"],
        ["Warm-up excluded", f"{A.WARMUP:.0f} s"],
        ["Circuit", f"{track.name}, {track.length:.0f} m"],
        ["Field sizes sampled", ", ".join(str(c) for c in space.get("n_cars_choices", []))],
        ["Weathers sampled", ", ".join(space.get("weathers", []))],
        ["Traffic density range", str(space.get("traffic_density"))],
        ["Track width multiplier", str(space.get("track_width_multiplier"))],
        ["Error-rate multiplier", str(space.get("error_rate_multiplier"))],
        ["Wall time", f"{(ov.get('wall_time_ms') or 0) / 1000:.1f} s"],
        ["Total simulated time", f"{(tot.get('total_simulated_seconds') or 0) / 3600:.1f} h"],
        ["Total agent-timesteps",
         f"{(tot.get('total_timesteps') or 0) * (tot.get('avg_cars') or 0):,.0f}"],
    ]))
    A_("")

    # ---- 3. Driver model ---------------------------------------------------
    A_("## 3. Multi-agent driver model")
    A_("")
    A_("Each agent carries a persistent behavioural profile. Across a batch the "
       "profile does not change; what varies run to run is a perturbation around "
       "it, scaled by that agent's own consistency and predictability. Every value "
       "below is a simulation parameter, not a measured property of any real driver.")
    A_("")
    A_(_table(
        ["Archetype", "Aggr.", "Risk", "Overtake", "Defend", "React (s)",
         "Late brake", "Consistency", "Error x"],
        [[ARCHETYPES[a]["label"], f"{ARCHETYPES[a]['aggression']:.2f}",
          f"{ARCHETYPES[a]['risk_tolerance']:.2f}",
          f"{ARCHETYPES[a]['overtake_willingness']:.2f}",
          f"{ARCHETYPES[a]['defensive_tendency']:.2f}",
          f"{ARCHETYPES[a]['reaction_time']:.2f}",
          f"{ARCHETYPES[a]['late_braking_tendency']:.2f}",
          f"{ARCHETYPES[a]['braking_consistency']:.2f}",
          f"{ARCHETYPES[a]['error_probability']:.2f}"]
         for a in ARCHETYPES]))
    A_("")

    # ---- 4. Assumptions ----------------------------------------------------
    A_("## 4. Model assumptions")
    A_("")
    A_("The registry below is the complete set of tunable numbers in the model. "
       "Entries marked *methodology* take their concept from established surrogate "
       "safety practice; entries marked *assumption* are choices made by this "
       "prototype and are not validated.")
    A_("")
    groups: dict[str, list] = {}
    for a in A.snapshot():
        groups.setdefault(a["group"], []).append(a)
    for g, items in groups.items():
        A_(f"### 4.{list(groups).index(g) + 1} {g}")
        A_("")
        A_(_table(["Parameter", "Value", "Unit", "Kind", "Reference"],
                  [[i["label"],
                    json.dumps(i["value"]) if isinstance(i["value"], dict)
                    else str(i["value"]),
                    i["unit"] or "—", i["kind"], i["reference"] or "—"]
                   for i in items]))
        A_("")

    # ---- 5. Methodology ----------------------------------------------------
    A_("## 5. Surrogate safety methodology")
    A_("")
    A_("Conflicts are detected from simulated trajectories using established "
       "surrogate safety measures rather than a bespoke danger score:")
    A_("")
    A_("- **Time to collision (TTC)** — computed in closed form from the projected "
       "constant-velocity motion of two oriented boxes in the curvilinear track "
       "frame. Longitudinal and lateral overlap are each an interval in time; TTC "
       "is the start of their intersection when that start is non-negative. The "
       f"conflict threshold is {A.TTC_CONFLICT_THRESHOLD} s, following SSAM's "
       "default.")
    A_("- **Post-encroachment time (PET)** — measured by conflict-cell occupancy: "
       "the elapsed time between one vehicle clearing a cell and the next entering "
       "it. This catches proximity that TTC misses entirely, because it requires no "
       "projected collision course.")
    A_("- **Closing speed, peak deceleration, evasive manoeuvres, contact, "
       "off-track excursions** — read directly from the trajectories.")
    A_("- **Conflict typing** — by the angle between vehicle headings at minimum "
       f"TTC, following SSAM's scheme (< {A.CONFLICT_ANGLE_REAR_END:.0f}° rear-end, "
       f"> {A.CONFLICT_ANGLE_CROSSING:.0f}° crossing, lane-change between), with "
       "racing-specific overtaking and defensive labels layered on from recorded "
       "agent intent.")
    A_("")
    A_("Agents act on a *delayed* view of their neighbours, implemented as a "
       "perception ring buffer indexed by each agent's own reaction time. The "
       "analyser, by contrast, measures ground truth — it is an omniscient reader "
       "of trajectories, as SSAM is a reader of a simulation's trajectory file.")
    A_("")
    A_("The **Simulation Conflict Severity Index (SCSI)** used for ranking is a "
       "constructed presentation aid, not a validated severity measure and not a "
       "probability. Its definition and weights are in section 4, raw metrics are "
       "reported alongside it everywhere, and every ranked view can be switched to "
       "raw minimum TTC.")
    A_("")

    # ---- 6. Conflict analysis ---------------------------------------------
    A_("## 6. Conflict analysis")
    A_("")
    rows = []
    for r in cb.get("by_type_and_severity", []):
        rows.append([r["conflict_type"], r["severity"], r["n"],
                     _fmt(r.get("mean_ttc"), 3), _fmt(r.get("mean_pet"), 3),
                     _fmt(r.get("mean_closing"), 2), r.get("collisions", 0),
                     r.get("evasive", 0)])
    if rows:
        A_(_table(["Conflict type", "Severity", "Count", "Mean TTC (s)",
                   "Mean PET (s)", "Mean closing (m/s)", "Contacts", "Evasive"], rows))
        A_("")
    if ov.get("min_ttc_distribution"):
        A_("Distribution of per-run minimum TTC:")
        A_("")
        A_(_table(["Band", "Runs", "Share"],
                  [[d["label"], d["count"], f"{d['fraction'] * 100:.1f}%"]
                   for d in ov["min_ttc_distribution"]]))
        A_("")

    # ---- 7. Hotspots -------------------------------------------------------
    A_("## 7. Circuit hotspots")
    A_("")
    A_(_table(["Location", "Turn", "Conflicts", "Per run", "Critical", "Contacts",
               "Median TTC (s)", "p05 TTC (s)", "Median PET (s)", "Width (m)"],
              [[s["name"], s["turn_number"] or "—", s["conflicts"],
                f"{s['conflicts_per_run']:.3f}", s["critical"], s["collisions"],
                _fmt(s["median_min_ttc"], 2), _fmt(s["p05_min_ttc"], 2),
                _fmt(s["median_min_pet"], 2), f"{s['width']:.1f}"]
               for s in hs.get("top_segments", [])[:10]]))
    A_("")
    A_("Counts are numbers of conflicts detected in simulated trajectories. A high "
       "count identifies a location where this model repeatedly produced "
       "safety-critical interactions under the sampled conditions; it does not "
       "establish that the corresponding corner is unsafe.")
    A_("")

    # ---- 8. Driver interactions -------------------------------------------
    A_("## 8. Driver interaction analysis")
    A_("")
    cells = [c for c in im.get("cells", []) if not c.get("sparse")
             and c.get("critical_per_co_present_run") is not None]
    cells.sort(key=lambda c: -c["critical_per_co_present_run"])
    seen = set()
    rows = []
    for c in cells:
        k = tuple(sorted([c["a"], c["b"]]))
        if k in seen:
            continue
        seen.add(k)
        rows.append([ARCHETYPES[c["a"]]["label"], ARCHETYPES[c["b"]]["label"],
                     c["co_present_runs"], c["conflicts"], c["critical"],
                     f"{c['critical_per_co_present_run']:.3f}",
                     _fmt(c["median_min_ttc"], 2),
                     (c["dominant_conflict_type"] or "—")])
        if len(rows) >= 12:
            break
    if rows:
        A_(_table(["Profile A", "Profile B", "Co-present runs", "Conflicts",
                   "Critical", "Critical per co-present run", "Median TTC (s)",
                   "Dominant type"], rows))
        A_("")
    A_("Rates are normalised by co-presence — the number of runs in which both "
       "profiles were on track — so they are not distorted by how often each "
       "profile was sampled into a field. No profile is 'dangerous': these are "
       "simulation parameterisations, and a higher rate means those two "
       "parameterisations produced more critical interactions in this model.")
    A_("")

    # ---- 9. Environmental sensitivity -------------------------------------
    A_("## 9. Environmental sensitivity")
    A_("")
    A_(_table(["Condition", "Runs", "Grip", "Vis.", "Conflicts/run",
               "Critical/run", "Contacts/run", "Excursions/run", "Mean min TTC (s)"],
              [[r["weather"], r["runs"], _fmt(r["grip"], 2), _fmt(r["visibility"], 2),
                _fmt(r["conflicts_per_run"], 2), _fmt(r["critical_per_run"], 2),
                _fmt(r["collisions_per_run"], 3), _fmt(r["off_track_per_run"], 2),
                _fmt(r["mean_min_ttc"], 2)]
               for r in env.get("by_weather", [])]))
    A_("")

    # ---- 10. Parameter sensitivity ----------------------------------------
    A_("## 10. Parameter sensitivity")
    A_("")
    A_(_table(["Parameter", "rho vs critical/run", "rho vs conflicts/run",
               "rho vs min TTC", "Range", "Runs"],
              [[p["label"], f"{p['correlations'].get('n_critical', 0):+.3f}",
                f"{p['correlations'].get('n_conflicts', 0):+.3f}",
                f"{p['correlations'].get('min_ttc', 0):+.3f}",
                f"{p['range'][0]} – {p['range'][1]}", p["n"]]
               for p in sens.get("parameters", [])[:14]]))
    A_("")
    A_(sens.get("method_note", ""))
    A_("")

    # ---- 11. Top discovered patterns --------------------------------------
    A_("## 11. Top recurring scenario patterns")
    A_("")
    if patterns:
        A_(_table(["#", "Zone", "Weather", "Traffic", "Conflict type",
                   "Occurrences", "Median TTC (s)", "Median PET (s)",
                   "Evasive", "Contact"],
                  [[p["rank"], p["location"], p["weather"], p["traffic_band"],
                    p["conflict_type"], f"{p['occurrences']} / {p['runs_evaluated']}",
                    _fmt(p["median_min_ttc"], 2), _fmt(p["median_min_pet"], 2),
                    f"{p['evasive_rate'] * 100:.0f}%",
                    f"{p['collision_rate'] * 100:.0f}%"]
                   for p in patterns]))
        A_("")
        A_("An occurrence count is the number of *simulated runs* in which this "
           "canonical situation produced a qualifying conflict. It is not a "
           "real-world probability. A pattern's key is its zone, weather, traffic "
           "band and conflict type; the behavioural profiles and human errors "
           "reported for it are the dominant composition *within* the pattern, with "
           "their share stated, not part of its definition.")
        A_("")
    else:
        A_("No patterns met the minimum recurrence threshold in this batch.")
        A_("")

    # ---- 12. Limitations ---------------------------------------------------
    A_("## 12. Limitations")
    A_("")
    A_("These limitations are specific to the configuration reported above, and "
       "they bound what the numbers in this report can support.")
    A_("")
    A_("**The vehicle model is a point mass.** There is no tyre model, no suspension, "
       "no thermal state, no aerodynamic map beyond a single speed-squared term on "
       f"each friction ceiling (gains {A.AERO_BRAKE_GAIN} braking, "
       f"{A.AERO_LATERAL_GAIN} lateral). Cornering speeds and braking distances are "
       "plausible in magnitude and ordering, and are not validated against any real "
       "vehicle.")
    A_("")
    A_("**Human error rates are dials, not measurements.** The rates in section 4 "
       "were chosen to produce a plausible spread of events, then adjusted when they "
       "produced implausible ones. They are not derived from incident data for any "
       "driver or series. Because conflict counts depend on them, the absolute "
       "numbers in this report inherit that arbitrariness — the comparisons between "
       "conditions are considerably more trustworthy than the levels.")
    A_("")
    A_("**Contact frequency is a model artefact as much as a finding.** Whether two "
       "cars touch depends on the fidelity of the lateral controller and on the "
       f"{A.SIDE_MIN_CLEARANCE:.2f} m clearance agents try to hold, both of which are "
       "modelling choices. Contact is reported split by energy for this reason.")
    A_("")
    A_("**One fictional circuit.** The layout is invented precisely so that no "
       "result here can be read as an assessment of a real, homologated venue. "
       "Nothing about the findings transfers to a real circuit.")
    A_("")
    A_(f"**A {A.SIM_DURATION:.0f}-second window, not a race.** All rates are per "
       "window. There is no tyre degradation over a stint, no fuel effect, no pit "
       "phase, no safety-car period, no flag or penalty system, and no "
       "race-position strategy beyond the immediate interaction.")
    A_("")
    A_("**The agent decision model is hand-written, not learned or calibrated.** "
       "Thresholds for committing to a pass, defending, and abandoning a move were "
       "tuned until the emergent behaviour looked like racing. Different plausible "
       "tunings would shift the results.")
    A_("")
    A_("**Surrogate measures are not crash predictions.** TTC and PET are "
       "established indicators of conflict in traffic safety research, validated "
       "in road-traffic contexts, not in motorsport. A low simulated TTC means two "
       "simulated trajectories nearly intersected in this model. Converting that "
       "into any statement about real-world crash likelihood would require "
       "validation work that has not been done here.")
    A_("")
    A_("**No validation against real incident data has been performed.** None is "
       "claimed.")
    A_("")

    # ---- 13. Conclusion ----------------------------------------------------
    A_("## 13. Conclusion")
    A_("")
    A_(f"The automated search executed {n_runs:,} multi-agent scenarios and reduced "
       f"them to a ranked set of recurring, safety-critical interaction patterns, "
       f"each traceable to the trajectories that produced it and replayable. "
       f"Professional motorsport organisations already perform circuit safety "
       f"analysis and driver-in-the-loop simulation at far higher fidelity than "
       f"anything here. What this prototype contributes is the layer above such a "
       f"simulator: automatic generation of a large, diverse scenario population, "
       f"surrogate-safety scoring of every run, and canonicalisation of the results "
       f"into patterns that recur — turning 'where is the dangerous corner' into "
       f"'which combinations of behaviour, traffic and conditions keep producing "
       f"dangerous interactions, and how often'.")
    A_("")
    A_("The findings are properties of this model. Establishing whether any of them "
       "corresponds to real-world risk would require a higher-fidelity vehicle "
       "model, behavioural parameters grounded in telemetry, and validation against "
       "recorded incidents.")
    A_("")

    # ---- References --------------------------------------------------------
    A_("## References")
    A_("")
    A_("1. FIA — Circuit Safety. https://www.fia.com/circuit-safety")
    A_("2. FIA — How the FIA has expanded circuit homologation to boost safety and "
       "grow participation (Circuit Safety Analysis System). "
       "https://www.fia.com/news/fia-safety-week-how-fia-has-expanded-circuit-homologation-boost-safety-and-grow-participation")
    A_("3. FIA — Activity Report 2024, Safety and Technological Development. "
       "https://activityreport2024.fia.com/sport-championships/safety-and-technological-development/")
    A_("4. FHWA — Surrogate Safety Assessment Model (SSAM) overview. "
       "https://www.fhwa.dot.gov/publications/research/safety/10020/")
    A_("5. FHWA — SSAM technical summary, FHWA-HRT-08-049. "
       "https://www.fhwa.dot.gov/publications/research/safety/08049/")
    A_("6. FHWA — SSAM user manual, FHWA-HRT-08-050. "
       "https://www.fhwa.dot.gov/publications/research/safety/08050/")
    A_("")

    markdown = "\n".join(S)
    return dict(
        batch_id=batch_id,
        markdown=markdown,
        sections=[l[3:] for l in S if l.startswith("## ")],
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        n_runs=n_runs,
    )
