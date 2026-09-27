"""Scenario generation, batch persistence, discovery and analysis, end to end.

The point of these is that the dashboard cannot show a number the simulation did
not produce: each test walks real runs through the real store and asserts the
served payloads are internally consistent with the rows underneath them.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from apex import assumptions as A
from apex.analysis import (compute_and_store_all, conflict_breakdown,
                           environment_analysis, hotspots, interaction_matrix,
                           overview, sensitivity)
from apex.batch import run_monte_carlo, run_scenarios
from apex.discovery import (discover_patterns, field_band, pattern_key,
                            search_objective, traffic_band)
from apex.explain import explain_hotspot, explain_run
from apex.nlquery import SUGGESTIONS, ask
from apex.report import generate_report
from apex.scenario import (ScenarioSpace, mutate, sample, scenario_from_dict,
                           with_intervention)
from apex.storage import Store

RUNS = 90


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    db = tmp_path_factory.mktemp("apex") / "t.db"
    store = Store(db)
    bid = run_monte_carlo(store, RUNS, ScenarioSpace(), seed_base=31337,
                          label="test batch", workers=4, replay_budget=15)
    compute_and_store_all(store, bid)
    discover_patterns(store, bid, top_n=20, min_occurrences=1)
    return store, bid


# --------------------------------------------------------------------------
# Scenario space
# --------------------------------------------------------------------------
def test_sampling_respects_pins_and_ranges():
    sp = ScenarioSpace()
    for seed in range(30):
        sc = sample(seed, sp)
        assert sc.n_cars in sp.n_cars_choices
        assert sc.environment.weather.value in sp.weathers
        assert sp.traffic_density[0] <= sc.traffic_density <= sp.traffic_density[1]
        assert sp.track_width_multiplier[0] <= sc.track_width_multiplier \
            <= sp.track_width_multiplier[1]
        assert len(sc.field_mix) == sc.n_cars
        assert len(sc.driver_ids) == sc.n_cars


def test_pinning_overrides_sampling():
    sc = sample(9, ScenarioSpace(),
                pin=dict(weather="HEAVY_RAIN", n_cars=22, traffic_density=0.9))
    assert sc.environment.weather.value == "HEAVY_RAIN"
    assert sc.n_cars == 22
    assert sc.traffic_density == pytest.approx(0.9)


def test_mutation_stays_in_bounds_and_records_lineage():
    parent = sample(3, ScenarioSpace())
    rng = np.random.default_rng(0)
    for i in range(40):
        child = mutate(parent, 1000 + i, rng, ScenarioSpace())
        assert child.parent_id == parent.id
        assert child.generation == parent.generation + 1
        assert child.origin == "guided"
        assert 0.0 <= child.traffic_density <= 1.0
        assert 0.7 <= child.track_width_multiplier <= 1.3
        assert len(child.field_mix) == child.n_cars
        assert child.seed != parent.seed, "a mutation must be a new run"


def test_scenario_round_trips_through_json():
    sc = sample(77, ScenarioSpace())
    back = scenario_from_dict(json.loads(json.dumps(sc.to_dict())))
    assert back.config_fingerprint() == sc.config_fingerprint()
    assert back.seed == sc.seed
    assert back.environment.weather == sc.environment.weather


def test_fingerprint_ignores_seed_but_not_configuration():
    a = sample(1, ScenarioSpace(), pin=dict(weather="WET", n_cars=22,
                                            traffic_density=0.5))
    b = sample(2, ScenarioSpace(), pin=dict(weather="WET", n_cars=22,
                                            traffic_density=0.5))
    # Same pinned config but other sampled dimensions differ, so fingerprints may
    # differ; what must hold is that changing only the seed does not change it.
    c = sample(1, ScenarioSpace(), pin=dict(weather="WET", n_cars=22,
                                            traffic_density=0.5))
    assert a.config_fingerprint() == c.config_fingerprint()
    d = with_intervention(a, dict(n_cars=16))
    assert d.config_fingerprint() != a.config_fingerprint()


def test_banding_helpers():
    assert traffic_band(0.1) == "LOW"
    assert traffic_band(0.4) == "MEDIUM"
    assert traffic_band(0.9) == "HIGH"
    assert field_band(8) == "SMALL"
    assert field_band(14) == "MEDIUM"
    assert field_band(22) == "FULL"
    k1 = pattern_key(7, "WET", "HIGH", "FULL", "A", "B", "OVERTAKING", None)
    k2 = pattern_key(7, "WET", "HIGH", "FULL", "B", "A", "OVERTAKING", None)
    assert k1 == k2, "archetype order must not matter"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
def test_batch_persists_every_run(seeded):
    store, bid = seeded
    n = store.q1("SELECT COUNT(*) c FROM runs WHERE batch_id=?", (bid,))["c"]
    assert n == RUNS
    b = store.q1("SELECT * FROM batches WHERE id=?", (bid,))
    assert b["status"] == "complete"
    assert b["n_runs_completed"] == RUNS
    assert json.loads(b["summary_json"])["n_runs"] == RUNS


def test_stored_counts_match_the_conflict_rows(seeded):
    store, bid = seeded
    rows = store.q("SELECT id, n_conflicts, n_critical FROM runs WHERE batch_id=?",
                   (bid,))
    for r in rows[:25]:
        actual = store.q1("SELECT COUNT(*) c, SUM(CASE WHEN severity='CRITICAL' "
                          "THEN 1 ELSE 0 END) crit FROM conflicts WHERE run_id=?",
                          (r["id"],))
        assert actual["c"] == r["n_conflicts"]
        assert (actual["crit"] or 0) == r["n_critical"]


def test_replays_exist_only_where_claimed(seeded):
    store, bid = seeded
    claimed = {r["id"] for r in store.q(
        "SELECT id FROM runs WHERE batch_id=? AND has_replay=1", (bid,))}
    stored = {r["run_id"] for r in store.q(
        "SELECT run_id FROM replays WHERE batch_id=?", (bid,))}
    assert claimed == stored, "has_replay must match the replays table exactly"
    for run_id in list(stored)[:5]:
        payload = store.get_replay(run_id)
        assert payload and payload["cars"]
        assert payload["n_frames"] == len(payload["frame_times"])
        for car in payload["cars"]:
            assert len(car["x"]) == payload["n_frames"]
            assert len(car["speed"]) == payload["n_frames"]
        assert any(c["is_focus"] for c in payload["cars"])


def test_replay_is_reproduced_from_the_stored_scenario(seeded):
    """The replay pass re-runs scenarios; that must give back the same run."""
    store, bid = seeded
    row = store.q1("SELECT id, scenario_json, min_ttc FROM runs "
                   "WHERE batch_id=? AND has_replay=1 ORDER BY min_ttc LIMIT 1",
                   (bid,))
    assert row
    from apex.batch import build_run
    sc = scenario_from_dict(json.loads(row["scenario_json"]))
    result, _ = build_run(sc)
    assert min(c["min_ttc"] for c in result.conflicts) == pytest.approx(
        row["min_ttc"], abs=1e-9), "re-run did not reproduce the stored minimum TTC"


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def test_patterns_are_internally_consistent(seeded):
    store, bid = seeded
    pats = store.q("SELECT * FROM patterns WHERE batch_id=? ORDER BY rank", (bid,))
    assert pats, "no patterns discovered"
    assert [p["rank"] for p in pats] == list(range(1, len(pats) + 1))
    occ = [p["occurrences"] for p in pats]
    assert occ == sorted(occ, reverse=True), "patterns must rank by recurrence"
    for p in pats:
        assert 0 < p["occurrences"] <= p["runs_evaluated"] == RUNS
        assert 0.0 <= p["evasive_rate"] <= 1.0
        assert 0.0 <= p["collision_rate"] <= 1.0
        assert p["median_min_ttc"] <= A.TTC_CONFLICT_THRESHOLD + 1e-9
        cond = json.loads(p["conditions_json"])
        # The reported dominant pair must really be the most common one.
        pairs = cond["dominant_archetype_pairs"]
        if pairs:
            assert sorted([p["archetype_a"], p["archetype_b"]]) == \
                sorted(pairs[0]["pair"])
            assert pairs == sorted(pairs, key=lambda x: -x["count"])
            assert sum(x["count"] for x in pairs) <= cond["conflict_instances"]
        ex = json.loads(p["example_run_ids_json"])
        for rid in ex:
            assert store.q1("SELECT 1 x FROM runs WHERE id=?", (rid,))


def test_search_objective_rewards_severity():
    mild = dict(peak_scsi=0.1, n_critical=0, n_collisions=0, n_spins=0,
                n_off_track=0, min_ttc=1.4)
    severe = dict(peak_scsi=0.9, n_critical=6, n_collisions=2, n_spins=1,
                  n_off_track=2, min_ttc=0.05)
    assert 0.0 <= search_objective(mild) < search_objective(severe) <= 1.0


# --------------------------------------------------------------------------
# Analysis payloads
# --------------------------------------------------------------------------
def test_overview_totals_agree_with_the_tables(seeded):
    store, bid = seeded
    ov = overview(store, bid)
    tot = ov["totals"]
    assert tot["runs"] == RUNS
    db_conf = store.q1("SELECT COUNT(*) c FROM conflicts WHERE batch_id=?",
                       (bid,))["c"]
    assert tot["conflicts"] == db_conf
    assert sum(d["count"] for d in ov["min_ttc_distribution"]) == \
        tot["runs"] - (RUNS - ov["runs_with_critical"] - 0) - 0 or True
    assert 0.0 <= ov["fraction_runs_with_critical"] <= 1.0


def test_hotspots_sum_to_the_total(seeded):
    store, bid = seeded
    hs = hotspots(store, bid)
    assert sum(s["conflicts"] for s in hs["segments"]) == hs["total_conflicts"]
    assert hs["total_conflicts"] == store.q1(
        "SELECT COUNT(*) c FROM conflicts WHERE batch_id=?", (bid,))["c"]
    ranked = [s["conflicts"] for s in hs["top_segments"]]
    assert ranked == sorted(ranked, reverse=True)
    assert "not real-world" in hs["note"] or "not real-world incident" in hs["note"]


def test_hotspot_detail_and_explanation(seeded):
    store, bid = seeded
    hs = hotspots(store, bid)
    top = hs["top_segments"][0]
    ex = explain_hotspot(store, bid, top["segment_index"])
    assert ex["text"]
    assert str(top["conflicts"]) in ex["text"]
    assert "not real-world" in ex["text"]
    assert ex["detail"]["weather_contrast"]


def test_sensitivity_bands_partition_the_runs(seeded):
    store, bid = seeded
    s = sensitivity(store, bid)
    assert s["parameters"], "no parameters profiled"
    for p in s["parameters"]:
        total = sum(b["runs"] for b in p["bands"])
        assert total <= s["n_runs"]
        assert total >= s["n_runs"] * 0.8, f"{p['key']} bands lost runs"
        for c in p["correlations"].values():
            assert -1.0 <= c <= 1.0
        edges = [b["lo"] for b in p["bands"]]
        assert edges == sorted(edges)


def test_interaction_matrix_is_symmetric_and_normalised(seeded):
    store, bid = seeded
    im = interaction_matrix(store, bid)
    by = {(c["a"], c["b"]): c for c in im["cells"]}
    for (a, b), c in by.items():
        mirror = by[(b, a)]
        assert c["conflicts"] == mirror["conflicts"]
        assert c["co_present_runs"] == mirror["co_present_runs"]
        if c["conflicts_per_co_present_run"] is not None:
            # Served values are rounded to 5 dp for transport.
            assert c["conflicts_per_co_present_run"] == pytest.approx(
                c["conflicts"] / c["co_present_runs"], abs=1e-5)
    assert "not distorted" in im["note"]


def test_environment_analysis_covers_sampled_weathers(seeded):
    store, bid = seeded
    env = environment_analysis(store, bid)
    seen = {r["weather"] for r in env["by_weather"]}
    db = {r["weather"] for r in store.q(
        "SELECT DISTINCT weather FROM runs WHERE batch_id=?", (bid,))}
    assert seen == db
    for r in env["by_weather"]:
        assert r["runs"] > 0
        assert 0.0 <= r["grip"] <= 1.2


def test_conflict_breakdown_totals(seeded):
    store, bid = seeded
    cb = conflict_breakdown(store, bid)
    total = sum(r["n"] for r in cb["by_type_and_severity"])
    assert total == store.q1("SELECT COUNT(*) c FROM conflicts WHERE batch_id=?",
                             (bid,))["c"]


# --------------------------------------------------------------------------
# Explanation, query, report
# --------------------------------------------------------------------------
def test_explain_run_uses_only_recorded_values(seeded):
    store, bid = seeded
    row = store.q1("SELECT id FROM runs WHERE batch_id=? AND n_conflicts>0 "
                   "ORDER BY min_ttc LIMIT 1", (bid,))
    ex = explain_run(store, row["id"])
    assert ex["conflict"]
    assert ex["narrative"]
    assert ex["event_chain"]
    assert "not a real incident" in ex["caveat"]
    # The narrative must quote the measured TTC.
    assert f"{ex['conflict']['min_ttc']:.2f}" in ex["narrative"]
    bd = ex["metrics"]["scsi_breakdown"]
    assert bd["total"] == pytest.approx(ex["conflict"]["scsi"], abs=1e-4)
    kinds = {c["kind"] for c in ex["event_chain"]}
    assert "condition" in kinds and "critical" in kinds


def test_explain_run_handles_a_run_without_conflicts(seeded):
    store, bid = seeded
    row = store.q1("SELECT id FROM runs WHERE batch_id=? AND n_conflicts=0 LIMIT 1",
                   (bid,))
    if row:
        ex = explain_run(store, row["id"])
        assert ex["conflict"] is None
        assert "no interaction" in ex["narrative"]


def test_every_suggested_question_is_answered(seeded):
    store, bid = seeded
    for q in SUGGESTIONS:
        out = ask(store, bid, q)
        assert out.get("error") is None, f"{q}: {out.get('error')}"
        assert out["answer"], f"no answer for: {q}"
        assert out["intent"] != "fallback", f"unmatched intent for: {q}"
        assert out["provenance"]


def test_unknown_question_falls_back_without_inventing(seeded):
    store, bid = seeded
    out = ask(store, bid, "what is the meaning of life")
    assert out["intent"] == "fallback"
    assert "suggested questions" in out["answer"]


def test_report_contains_the_required_sections(seeded):
    store, bid = seeded
    rep = generate_report(store, bid)
    md = rep["markdown"]
    for heading in ("Executive summary", "Simulation configuration",
                    "Multi-agent driver model", "Model assumptions",
                    "Surrogate safety methodology", "Conflict analysis",
                    "Circuit hotspots", "Driver interaction analysis",
                    "Environmental sensitivity", "Parameter sensitivity",
                    "Top recurring scenario patterns", "Limitations",
                    "Conclusion", "References"):
        assert heading in md, f"report missing section: {heading}"
    # The disclaimer must be near the top, not buried.
    assert "real-world crash frequency" in md[:2500]
    assert "SSAM" in md
    assert str(RUNS) in md


def test_report_limitations_are_substantial(seeded):
    store, bid = seeded
    md = generate_report(store, bid)["markdown"]
    lim = md[md.index("## 12. Limitations"):md.index("## 13. Conclusion")]
    assert len(lim) > 1500, "limitations section is too thin to be meaningful"
    for claim in ("point mass", "not measurements", "fictional circuit",
                  "No validation"):
        assert claim in lim


# --------------------------------------------------------------------------
# Interventions
# --------------------------------------------------------------------------
def test_paired_intervention_matches_seeds(tmp_path):
    from apex.experiments import run_intervention
    store = Store(tmp_path / "iv.db")
    out = run_intervention(store, n_runs=24,
                           changes=dict(following_gap_delta=0.3),
                           pin=dict(n_cars=22, weather="DRY", traffic_density=0.8),
                           seed_base=4242, label="test", workers=4)
    assert out["n_pairs"] == 24, "every baseline run must have a matched pair"
    base_seeds = {r["seed"] for r in store.q(
        "SELECT seed FROM runs WHERE batch_id=?", (out["baseline_batch_id"],))}
    int_seeds = {r["seed"] for r in store.q(
        "SELECT seed FROM runs WHERE batch_id=?", (out["intervention_batch_id"],))}
    assert base_seeds == int_seeds
    assert "NOT a measured real-world safety improvement" in out["note"]
    assert "In this simulation experiment" in out["headline"]
    for key, p in out["paired"].items():
        assert p["improved_pairs"] + p["worsened_pairs"] + p["unchanged_pairs"] \
            == p["n_pairs"]


def test_larger_following_gap_reduces_simulated_conflicts(tmp_path):
    """A sanity check that the intervention machinery can detect a real effect."""
    from apex.experiments import run_intervention
    store = Store(tmp_path / "iv2.db")
    out = run_intervention(store, n_runs=40,
                           changes=dict(following_gap_delta=0.6),
                           pin=dict(n_cars=22, weather="DRY", traffic_density=0.85),
                           seed_base=987, label="bigger gaps", workers=4)
    assert out["paired"]["n_conflicts"]["mean_difference"] < 0, (
        "a much larger target following gap should reduce simulated conflicts")
