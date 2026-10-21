# CarbonShift AI — Design

## Shape

```
operator message
   -> HackathonAgent.chat()
      -> Strands Agent (Amazon Bedrock) with tools: list_workloads, profile_workload,
         generate_candidates, estimate_impact
      -> when the operator asks to schedule workload W:
           scheduler.generate_candidates(W)      # deterministic: windows x eligible regions
             -> hard-constraint filter (deadline, capacity, eligibility, flexibility)  [code]
             -> feasible set (0..N candidates)
           CarbonShiftDecision.select(W, feasible)   # the seam
             -> if len(feasible) <= 1: pick it, no decider call
             -> else: Decider.ask(state, {"best_candidate": choice(ids -> descriptions)})
             -> confidence check + independent re-validation + fallback
      -> Bedrock explains the selected schedule, trade-offs and impact
```

The seam is **outside** the Strands tool loop: `HackathonAgent.chat()` detects a scheduling
request, runs the scheduler and the decision, then feeds the validated result back to the LLM for
the explanation. Every decider call appends one record to `decision.log`, surfaced in
`chat()["decisions"]`.

## State text layout (exactly what the eval cases use)

```
--- WORKLOAD ---
id: W-ANALYTICS-01
name: Nightly revenue rollup
type: analytics
priority: normal
flexible: yes
deadline_hours_remaining: 14
runtime_hours: 2.0
avg_power_kw: 3.5

--- FEASIBLE CANDIDATES (hard constraints already enforced) ---
C1: run now | region ap-south-1 | starts in 0.0 h | finishes 2.0 h before deadline | carbon 0.71 kgCO2e/kWh | est 4.97 kgCO2e
C2: shift later | region ap-south-1 | starts in 6.0 h | finishes 6.0 h before deadline | carbon 0.52 kgCO2e/kWh | est 3.64 kgCO2e
C3: shift+move | region eu-west-1 | starts in 4.0 h | finishes 8.0 h before deadline | carbon 0.23 kgCO2e/kWh | est 1.61 kgCO2e

--- OBJECTIVE ---
Prefer the lowest estimated emissions while keeping a safe deadline margin and respecting the
workload's priority. Avoid options that cut the deadline margin thin for little carbon gain.
```

- `est kgCO2e` is computed in code (energy x intensity); it is a fact in the state, not something
  the model invents.
- Candidate IDs are stable (`C1`, `C2`, ...) and map back to the candidate objects by index.

## The typed question

```python
QUESTIONS = {
  "best_candidate": Decider.choice(
    "Which candidate is the best schedule for this workload, balancing lower estimated carbon "
    "emissions against a safe deadline margin and the workload's priority?",
    { "C1": "...per-candidate description, filled in per request...", ... }),
}
```

The option descriptions are built per request from the feasible candidates (the kit's `choice`
allows options to change per call). Each description states the window, region, deadline margin
and estimated emissions in prose, so the model weighs the trade-off rather than reading a label.

## Thresholds and actions (in code we own)

| Situation | Action | Verdict logged |
|---|---|---|
| 0 feasible candidates | refuse to schedule; ask operator to relax constraints | `infeasible` |
| 1 feasible candidate | select it, no decider call | `only_option` |
| >=2 feasible, confidence >= 0.6, choice valid & re-validated | select the chosen candidate | `decider` |
| confidence < 0.6 | select lowest-emissions feasible candidate, flag for review | `low_confidence_fallback` |
| chosen id not in option set, or fails re-validation | deterministic fallback | `invalid_fallback` |
| decider raises / unavailable | deterministic fallback | `error_fallback` |

`CONFIDENCE_THRESHOLD = 0.6` is a module constant, documented as tunable.

## Emissions model (documented assumptions)

- `energy_kwh = avg_power_kw * runtime_hours`
- `emissions_kg = energy_kwh * carbon_intensity_kg_per_kwh`
- `avg_power_kw` is a per-workload synthetic estimate of average draw across its instances.
- Carbon intensity is a synthetic per-region, per-time-window value in `agent/data/`.
- Scope: operational electricity of the workload only. Not embodied carbon, PUE, or AWS's whole
  footprint. All synthetic, clearly labelled.
- Baseline = the immediate-run candidate (run now, in the workload's home region).

## Tools (agent/tools.py)

- `list_workloads()` — pending workloads awaiting scheduling.
- `profile_workload(workload_id)` — runtime, power, deadline, priority, flexibility, eligibility.
- `generate_candidates(workload_id)` — feasible candidates with per-candidate energy & emissions
  (calls the scheduler; hard constraints already applied).
- `estimate_impact(workload_id, candidate_id)` — baseline vs selected emissions, abs & % saved.

## Scheduler (agent/scheduler.py) — deterministic, testable

- `Workload`, `Candidate` dataclasses.
- `generate_candidates(w)` -> all windows x eligible regions, each with energy/emissions.
- `feasible(w, candidates)` -> filter by deadline, capacity, eligibility, flexibility.
- `baseline(w)` -> the immediate-run candidate.
- `impact(baseline, chosen)` -> dict with kWh, kg, abs & % difference, deadline compliance.
- `render_state(w, feasible)` -> the exact state text above.
- `safe_choice(feasible)` -> lowest-emissions feasible candidate (the deterministic fallback).

## Eval-case plan (agent/eval_cases.jsonl)

At least 24 cases, ~half `test`. Each: `{"state": <render_state output>, "expected":
{"best_candidate": "C?"}, "split": "tune"|"test"}`. The label is the candidate a careful operator
picks under the objective (lowest emissions with a safe margin; not a thin-margin option for a
tiny gain). Coverage:
- flexible analytics: a clearly cleaner later/other-region window should win (several variants);
- deadline-constrained batch: the cleanest option that still keeps a safe margin wins, not the
  cleanest-but-risky one (near-misses where the greenest option cuts the margin too thin);
- urgent / inflexible: only one feasible candidate (run now) — tests the `only_option` path and
  also appears as a labelled case where C1 is correct;
- ties and near-ties where two windows have close emissions but different deadline margins.

## Wiring class

`CarbonShiftDecision` (not an InterventionHandler — the seam is pre/post the tool loop):
- `select(workload, feasible) -> Selection` with the chosen `Candidate`, verdict, probabilities,
  confidence, decider_ms, fallback flag.
- appends one record per decider call to `self.log`.
- keeps `QUESTIONS` module-level so the benchmark can import `agent.decision:QUESTIONS` — note the
  benchmark builds options from the same `render_state` layout the cases use (the question's
  `criteria` for benchmarking is a fixed C1..Cn id->meaning map; see decision.py).
