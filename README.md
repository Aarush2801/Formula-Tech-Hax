# APEX — Multi-Agent Motorsport Safety Stress Tester

Automated generation and surrogate-safety analysis of thousands of multi-driver
racing scenarios, searching for **recurring safety-critical interactions**.

> Everything this application reports is an output of a simulation model under
> stated assumptions. No figure here is a real-world crash probability, an
> incident rate, or an assessment of a real circuit, driver or series. No
> validation against recorded incident data has been performed, and none is
> claimed.

---

## What this is

This is **not** a replacement for a professional motorsport simulator, and it
does not suggest that teams or the FIA fail to perform simulation and circuit
safety analysis — they do, at far higher fidelity than anything here.

What this prototype adds is the layer *above* such a simulator:

```
              ┌─────────────────────┐
              │ SCENARIO GENERATOR  │  sample / mutate the parameter space
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │  22 DRIVER AGENTS   │  persistent behavioural profiles
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │  RACING ENGINE      │  deterministic, vectorised, 20 Hz
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ TRAJECTORY LOGGER   │  full state, every agent, every step
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │  SAFETY ANALYSER    │  TTC · PET · conflict typing (SSAM-style)
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ DISCOVERY ENGINE    │  canonicalise → count recurrence → mutate
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ ANALYTICS ENGINE    │  hotspots · sensitivity · interactions
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ SAFETY DASHBOARD    │  11 screens, replay, what-if, report,
              └─────────────────────┘  plus 5 Apex Passport screens
```

It turns *"where is the dangerous corner?"* into *"which combinations of
behaviour, traffic and conditions keep producing dangerous interactions, how
often, and what happens if we change one?"*

---

## Why it exists

A high-fidelity simulator answers "what happens in **this** scenario" extremely
well. It does not, by itself, tell you **which scenarios to run**. A human picks
them, and a human picks the ones they already suspect.

The gap this prototype probes is the search layer: generate a large, diverse
population of multi-agent scenarios automatically, score every one of them with
established surrogate safety measures, reduce the results to canonical situations,
and report the ones that keep recurring — together with the trajectory that
produced each, so a finding can be watched and explained rather than taken on
trust.

---

## Quick start

Requirements: Python 3.11+, Node 20+.

```bash
# 1. Backend
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt

# 2. Seed a database (≈22 min on 10 cores for the full 10,000-run demo;
#    use --runs 2000 for a ≈4 min version)
cd backend
../.venv/bin/python -m apex.cli demo --runs 10000 --generations 8 --population 80

# 3. Serve the API
../.venv/bin/uvicorn apex.api:app --port 8000

# 4. Frontend, in another terminal
cd frontend
npm install
npm run dev          # http://localhost:3000
```

The dashboard is empty until a batch exists — by design. Nothing in the UI is
mocked, so there is nothing to show before the engine has produced trajectories.

The Apex Passport screens (under **Apex Passport** in the side menu, starting at
<http://localhost:3000/passport>) do not need a seeded batch — set up a car in
the Garage and run a stress test from there. See [Apex Passport](#apex-passport).

### CLI

Run from `backend/`:

```bash
P="../.venv/bin/python -m apex.cli"

$P info                        # circuits, assumption registry, recent batches
$P batch -n 2000               # Monte Carlo search
$P guided --generations 8      # adversarial search, seeded from the last batch
$P experiment all --runs 150   # the controlled experiment suite
$P whatif --changes '{"following_gap_delta":0.15}' -n 200
$P report --out report.md      # the stress-test write-up
```

---

## Methodology

### Surrogate safety measures

Conflicts are detected from simulated trajectories using established surrogate
safety measures rather than an invented danger score. The reference is FHWA's
Surrogate Safety Assessment Model (SSAM).

**Time to collision (TTC)** is computed in closed form. Two cars are oriented
boxes in the curvilinear track frame; projecting both at constant velocity, the
longitudinal extents overlap during one interval in *t* and the lateral extents
during another. TTC is the start of the intersection of those two intervals, when
that start is non-negative. The conflict threshold is SSAM's default of **1.5 s**,
inherited rather than invented.

**Post-encroachment time (PET)** is measured by conflict-cell occupancy — the
track is diced into cells and PET is the elapsed time between one car clearing a
cell and the next entering it. This requires no projected collision course, so it
catches proximity that TTC misses entirely.

**Conflict typing** follows SSAM's scheme, by the angle between the two vehicles'
headings at minimum TTC: below ~30° rear-end, above ~85° crossing, lane-change in
between. Racing-specific *overtaking* and *defensive* labels are layered on top
from recorded agent intent, and are clearly a prototype addition.

Also recorded directly from trajectories: closing speed, peak deceleration,
evasive manoeuvres, contact (split by energy), off-track excursions and barrier
strikes.

A composite **Simulation Conflict Severity Index** exists for ranking. It is
labelled as constructed everywhere it appears, its weights are published on the
Model Assumptions screen, raw metrics are shown beside it, and every ranked view
can be switched to raw minimum TTC.

### The agents

Twenty-two agents advance together in synchronised 20 Hz timesteps. Each carries a
persistent behavioural profile — aggression, risk tolerance, overtake willingness,
defensive tendency, reaction time, braking consistency, late-braking tendency,
line-change tendency, error probability, predictability, pace.

Across a batch **the profile does not change**. What varies run to run is a
perturbation around it, scaled by that agent's own consistency and predictability:
a High Consistency agent barely moves from its profile, an Unpredictable one
varies several times as much. Randomness represents uncertainty about how a
personality expresses itself on a given lap, not a personality re-rolled each run.

Reaction time is a genuine **perception delay**, implemented as a ring buffer:
each agent acts on the world as it was one of its own reaction times ago. The
analyser, by contrast, measures ground truth — it is an omniscient reader of
trajectories, exactly as SSAM reads a simulation's trajectory file.

One deliberate exception: lateral separation from a car *already alongside* is
judged on true position, not the delayed view. Reaction time models the cost of
reading a situation developing at distance; a car two metres away is sensed
peripherally and continuously. Applying the delay there made separation oscillate
by more than the slack that exists before two 2.0 m cars touch, and a third of all
committed passes ended in contact as a result.

### Scenario generation and discovery

`sample()` draws over weather, grip, visibility, tyre condition, field size,
traffic density, grid spread, pace spread, track width, error rates and the
archetype composition of the field. `mutate()` perturbs an existing scenario for
the guided search. `with_intervention()` copies a scenario with named parameters
changed **and the seed preserved** — the basis of the what-if lab.

Discovered patterns are keyed on **zone × weather × traffic band × conflict type**.
An earlier version also keyed on the archetype pair, field size and dominant
error; that pushed the key space past three million combinations and nothing ever
recurred. The archetype pair and dominant error are still reported — as the
dominant *composition within* each pattern, with their share stated, which is both
more useful and more honest.

Each pattern reports two numbers: the raw count (of all runs) and the rate within
the runs actually drawn in its weather and traffic band. The raw count partly
reflects how often that band was sampled, so the conditional rate is the fairer
comparison between patterns.

### Guided search

Random sampling spends most of its budget on scenarios that produce nothing. The
guided search keeps an elite set of scenarios that produced severe conflicts and
mutates around them. Two safeguards stop it collapsing onto a single lucky draw
and reporting it as recurrence: mutation redraws the seed, and elite selection is
diversity-aware — the best scenario *per coarse signature*, not the best N overall.

The objective is named as a search objective. Maximising it locates interesting
regions of the parameter space and says nothing about real-world risk.

---

## Reproducibility

A run is fully determined by its scenario, and a scenario by its seed plus the
space it was drawn from. Re-running reproduces trajectories bit-for-bit.

This is load-bearing, not a nicety: the what-if lab compares seed-matched pairs,
and replay windows are generated in a **second pass** that re-runs stored
scenarios rather than carrying trajectory arrays through the batch.

The test suite includes a regression test that runs the same scenario in two
subprocesses under **different `PYTHONHASHSEED` values**. That test exists because
determinism was genuinely broken once: a `set` of error kinds was being iterated
while drawing randoms, so the RNG stream depended on hash ordering and diverged
between processes. The ordered-tuple fix is a one-line change; finding it was not.

---

## Performance

The engine is vectorised **across agents**, not across runs. All 22 cars advance
together, and the pairwise interaction structure the whole study is about — a
22×22 gap / closing-speed / TTC matrix — is 484 elements, which NumPy evaluates
essentially for free. A 75 s run at 20 Hz is 1,500 synchronised rounds costing
single-digit milliseconds of array work, rather than ~35,000 per-agent Python calls.

Measured on an Apple M4 (6 performance + 4 efficiency cores), 10 worker processes:

| | |
|---|---|
| Single 22-car, 75 s run | ~0.6 s |
| Throughput | ~8–11 runs/s |
| **10,000-run batch** | **~20 min**, including a 500-run replay pass |
| Database | ~115 MB for the full demo seed (10,000 Monte Carlo + 640 guided runs) |

Full trajectories are retained only in a window around interesting conflicts.
Keeping everything would be gigabytes per batch, nearly all of it cars driving
uneventfully.

---

## Repository layout

```
backend/apex/
  assumptions.py   every tunable number, with a provenance label
  models.py        the data contract between layers
  track.py         segment specs → closed centreline; curvilinear lookups; zones
  circuits.py      authored circuits (fictional, deliberately)
  drivers.py       persistent profiles, per-run perturbation, team-driver overrides
  environment.py   weather → grip / visibility / spray
  errors.py        human-error events with persistence
  engine.py        the timestep simulation — deterministic, vectorised, no LLM
  safety.py        TTC, PET, conflict typing, severity, SCSI
  replay.py        trajectory-window extraction
  scenario.py      the searchable space: sampling, mutation, intervention
  batch.py         parallel execution and persistence
  discovery.py     pattern canonicalisation and guided search
  analysis.py      hotspots, sensitivity, interaction matrix, environment
  explain.py       deterministic causal-chain reconstruction
  nlquery.py       natural-language questions → fixed, auditable SQL
  experiments.py   the controlled experiment suite and paired-seed what-if
  report.py        the research-style stress-test report
  live.py          single-run playback for the live view
  storage.py       SQLite
  api.py           HTTP surface (REST + SSE)
  jobs.py          shared background-job registry (batches, searches, stress tests)
  cli.py           command line

  # Apex Passport
  car_profiles.py  car specification + illustrative class presets
  passport.py      cars, parts, team driver, hash-chained history
  wear.py          kerb strikes / contacts → predicted % life used per part
  stress_test.py   N seeded races with the team car, aggregated per part
  insurance.py     policy conditions, insurer summary, incidents, claim/evidence packs
  passport_api.py  the passport HTTP routes (mounted by api.py)
backend/tests/     152 tests across 11 files
frontend/src/
  app/             11 simulator screens; app/passport/ holds the 5 Passport screens
  components/      UI primitives, charts, circuit map, replay viewer, passport widgets
  lib/             typed API clients, theme vocabulary, formatting, state
```

The layering is deliberate: **the physics can be replaced without touching
anything above it**, as long as the new engine emits the same trajectory,
vehicle-state and safety-event records.

---

## The AI layer

There is no language model in the simulation. Every decision in `engine.py` is
closed-form arithmetic on NumPy arrays, and no agent consults anything to decide
whether to brake.

Above the simulation:

- **Incident explanation** reconstructs a causal chain deterministically from the
  recorded trajectory, errors and decisions. Every clause traces to a recorded
  number, so there is nothing to invent.
- **Ask the simulator** is a rule-based intent router over *fixed, reviewed SQL
  queries*, not text-to-SQL. Each answer carries the query that produced it so it
  can be checked.

Both were built this way on purpose. An explanation of a safety-critical
interaction is exactly the place where a fluent guess is most damaging, and the
deterministic version is auditable line by line.

---

## Apex Passport

A digital passport for **one team's race car**, built on top of the simulator
without changing how any existing run behaves. It keeps the car's spec, part
condition, team driver and history in one place, uses the simulator to
stress-test that car before its next race, and assembles evidence an insurer can
read.

> Everything it produces is supporting evidence from simulated and recorded
> history. It is **not** an insurance quote, a claim decision, or a real-world
> crash probability — and every screen and payload says so.

### The five screens

| Screen | What it does |
|---|---|
| **Garage** | Create a car from a class preset (F1 2026, F2, F3, F4, Formula E, Formula Student) and adjust its spec. Choose its team driver: an archetype, with any of 11 traits adjusted by slider. |
| **Passport** | Life used per part against the 70% (inspect) and 90% (replace) thresholds, recording a part replacement, policy conditions, chain verification and the full history. |
| **Stress test** | Race the car N times (default 200) at a chosen circuit and weather, each against a different seeded field. |
| **Readiness** | The latest stress test: predicted life used per part (lowest / median / highest across the races), replace-or-inspect recommendations, an illustrative cost forecast, and the closest calls, each linked to its replay. |
| **Insurance** | Insurer summary, policy conditions, incident logging, per-incident claim packs, and the evidence pack (printable HTML or JSON). |

### How it works

**The team car.** A stress-test scenario puts the car in grid slot 1 with its
own physics (mass, power, grip, downforce, drag, braking) and its own driver;
the other 21 cars are the normal field. A scenario without a team car takes
exactly the code path it always did. Tests assert that a team car built from
the default assumptions gets exactly the default braking and cornering limits,
and that the other cars' physics are untouched. Stress-test
runs are ordinary runs, so they also show up in Replay and every analysis screen.

**The team driver.** Each car stores its driver as an archetype plus optional
per-trait overrides, clamped to bounds that span the archetype catalogue. Saving
a driver change is logged to the history, so the driver behind any stress test
can be audited later.

**Wear.** Each simulated race's kerb strikes and contacts become a predicted
increment of % life used. Harder hits cost disproportionately more (kerb wear
grows with severity squared; contact wear grows with impact speed and triples
for a severe contact), and load goes to the side of the car that was struck.
Parts tracked: four suspension corners, wheels, brakes, harness and seat.

**Tamper-evident history.** Every history event stores a SHA-256 hash of its own
content plus the previous event's hash. Verification recomputes the chain from
what is stored; editing an old event, even with a forged hash for that one row,
breaks the chain at that point.

**Incidents and claim packs.** Logging an incident freezes the car's part
condition at that moment. The claim pack compares that frozen "before" with the
current condition, so pre-existing wear and new damage can't be confused.

### API

All under `/api`, mounted from `passport_api.py`:

| Route | |
|---|---|
| `GET /car-presets` | class presets and the driver-trait catalogue |
| `GET /cars` · `POST /cars` | list / create cars (optionally with a spec and team driver) |
| `PUT /cars/{id}/driver` | save the team driver (logged to history) |
| `GET /cars/{id}/passport` | car, parts, history, chain verification, policy conditions |
| `POST /cars/{id}/parts/{part}/replace` | record a part replacement |
| `GET /cars/{id}/verify` | verify the history chain |
| `POST /cars/{id}/stress-test` · `GET /stress-test/{job_id}` | start / poll a stress test |
| `GET /cars/{id}/stress-tests/latest` | the latest stress-test result |
| `POST /cars/{id}/incidents` · `GET /cars/{id}/incidents` | log / list incidents |
| `GET /cars/{id}/claim-pack/{incident_id}` | before/after claim pack |
| `GET /cars/{id}/insurer-summary` | plain-English insurer summary |
| `GET /cars/{id}/evidence-pack?format=html` | evidence pack (`json` by default) |

### Passport limitations

- **Car physics are illustrative.** Class presets have plausible orderings, not
  manufacturer figures.
- **Kerb strikes are a proxy.** The circuits have no kerb geometry, so a strike
  is inferred from running past 85% of the half-width while still on track.
- **Wear rates are dials.** Every wear, cost and threshold figure is a labelled
  assumption in `assumptions.py` (group "Apex Passport"), not a measured curve.
- **Close calls are field-wide.** A stress test's close calls are races in which
  *any* two cars came within 0.8 s TTC, not only pairs involving the team car;
  the replay shows who was involved.
- **Races and inspections have no screen yet.** The history model supports
  them, and the inspection-interval condition counts them, but they can only be
  recorded from code (`passport.record_event`) for now.
- **Policy conditions are illustrative**, not the wording of any real policy.

---

## Limitations

These bound what anything in this repository can support.

- **The vehicle model is a point mass.** No tyre model, no suspension, no thermal
  state, no aerodynamic map beyond a single speed-squared term on each friction
  ceiling. Cornering speeds and braking distances are plausible in magnitude and
  ordering, and are validated against nothing.
- **Human error rates are dials, not measurements.** They were chosen to produce a
  plausible spread of events, then adjusted when they produced implausible ones
  (the spin rate was 70× too high in the first version). Absolute conflict counts
  inherit that arbitrariness. Comparisons *between* conditions are considerably
  more trustworthy than the levels.
- **Contact frequency is partly a model artefact.** Whether two cars touch depends
  on the fidelity of the lateral controller and on the clearance agents try to
  hold. Contact is reported split by energy for that reason.
- **One fictional circuit** (plus a second for cross-circuit comparison). The
  layout is invented precisely so no result can be read as an assessment of a
  real, homologated venue.
- **A 75-second window, not a race.** No tyre degradation over a stint, no fuel
  effect, no pit phase, no safety car, no flags or penalties, no strategy beyond
  the immediate interaction.
- **The decision model is hand-written**, not learned or calibrated. Thresholds
  were tuned until the emergent behaviour looked like racing. Other plausible
  tunings would shift the results.
- **Conflict rate declines across the window** because the field starts bunched
  and strings out. The first 8 s are excluded as a grid artefact; the remaining
  decline is real behaviour of a rolling pack, not a bug, but it means rates are
  per-window and not per-lap.
- **Surrogate measures are not crash predictions.** TTC and PET are validated as
  conflict indicators in *road-traffic* research, not motorsport. A low simulated
  TTC means two simulated trajectories nearly intersected in this model.

---

## One finding worth stating plainly

In the seeded 10,000-run batch, wetter conditions produced **fewer but closer**
conflicts than dry, alongside markedly more off-track excursions.

That runs against the intuition the project was built around. The mechanism is
visible in the engine: lower grip lowers cornering speeds, which shrinks the speed
differentials that trigger overtake attempts, so fewer interactions develop — but
the ones that do have less braking margin, and more cars simply run out of road.

It is reported as measured. The Environment screen states it in those terms rather
than adjusting the model until it agrees with expectation.

---

## References

Methodological references. Citing them is not a claim of equivalence with them.

1. FIA — Circuit Safety. <https://www.fia.com/circuit-safety>
2. FIA — How the FIA has expanded circuit homologation to boost safety and grow
   participation (Circuit Safety Analysis System).
   <https://www.fia.com/news/fia-safety-week-how-fia-has-expanded-circuit-homologation-boost-safety-and-grow-participation>
3. FIA — Activity Report 2024, Safety and Technological Development.
   <https://activityreport2024.fia.com/sport-championships/safety-and-technological-development/>
4. FHWA — Surrogate Safety Assessment Model overview.
   <https://www.fhwa.dot.gov/publications/research/safety/10020/>
5. FHWA — SSAM technical summary, FHWA-HRT-08-049.
   <https://www.fhwa.dot.gov/publications/research/safety/08049/>
6. FHWA — SSAM user manual, FHWA-HRT-08-050.
   <https://www.fhwa.dot.gov/publications/research/safety/08050/>

Architectural inspiration for the multi-agent round structure, event logging,
reproducible runs and batch-analysis dashboard was taken from
<https://github.com/leakyhose/agent-economy>. None of its domain mechanics are
used here.

---

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest tests/ -q
```

152 tests across eleven files. The simulator:

- `test_safety_metrics.py` — TTC against closed-form hand calculations in every
  regime (rear-end, lateral-only, already-overlapping, diverging, lap wraparound),
  PET cell occupancy, conflict typing, the severity ladder, SCSI bounds.
- `test_determinism.py` — seed reproducibility, cross-process reproducibility
  under randomised hash seeds, perturbation preserving agent identity.
- `test_engine.py` — circuit closure, corner-speed ordering, racing-line validity,
  physical bounds on state, error rates landing near their configured values,
  monotonic response to traffic density and field size, contact rarity in benign
  conditions.
- `test_pipeline.py` — scenario sampling and mutation bounds, batch persistence
  matching the rows beneath it, replay reproduction, pattern-record consistency,
  analysis payloads summing correctly, every suggested query answering, report
  completeness, paired-seed interventions.

The Apex Passport:

- `test_car_profiles.py` — no team car means no change; a reference-spec team
  car gets exactly the default physics limits; other cars are untouched; a
  lighter, grippier car corners faster; presets are well-formed.
- `test_team_driver.py` — trait overrides are applied, clamped and persisted;
  driver changes are chained into history; old databases migrate in place; stress
  tests use the saved driver.
- `test_passport.py` — part initialisation and thresholds, replacement logging,
  hash chaining, and tamper detection (edited details, and a forged hash).
- `test_wear.py` — severity scaling, side attribution, and that a contact can
  never restore life.
- `test_stress_test.py` — full report shape, determinism for a fixed seed,
  worn parts raising predictions, history logging, close calls matching the
  replays that exist.
- `test_insurance.py` — policy-condition states, the insurer summary, the
  incident snapshot staying frozen, claim packs and evidence packs.
- `test_passport_api.py` — every passport route, including the stress-test job
  lifecycle and error cases, alongside the existing API.
