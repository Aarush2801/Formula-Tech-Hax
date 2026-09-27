"""APEX — multi-agent motorsport safety stress tester.

Layered so the physics can be replaced without touching anything above it:

    assumptions   every tunable number, with a provenance label
    models        the data contract between layers
    track         geometry: segment specs -> closed centreline, curvilinear lookups
    circuits      authored circuit definitions
    drivers       persistent behavioural profiles and per-run perturbation
    environment   weather -> grip / visibility / spray
    errors        human-error events with persistence
    engine        the timestep simulation (deterministic, vectorised, no LLM)
    safety        surrogate safety measures: TTC, PET, conflict typing
    replay        trajectory-window extraction for the replay viewer
    scenario      the searchable scenario space: sampling, mutation, intervention
    batch         parallel execution and persistence
    discovery     pattern canonicalisation and guided search
    analysis      hotspots, sensitivity, interaction matrix, environment
    explain       deterministic causal-chain reconstruction
    nlquery       natural-language questions -> fixed, auditable SQL
    experiments   the controlled experiment suite and paired-seed what-if
    report        the research-style stress-test report
    live          single-run playback for the live view
    storage       SQLite
    api           HTTP surface
"""

__version__ = "0.1.0"
