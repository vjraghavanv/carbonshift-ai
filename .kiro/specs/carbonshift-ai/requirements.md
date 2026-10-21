# CarbonShift AI — Requirements

**Tagline:** Schedule Smarter. Compute Cleaner.
**Team:** Koodal AI Labs
**Decision pattern:** carbon-aware schedule selection — `choice` — tag `#tool-selection`
**Generative model:** Amazon Bedrock (the agent's conversation and explanations)
**Decision model:** Strands Decider 2B (the bounded candidate choice)

## Problem

Many cloud workloads (batch analytics, report generation, non-urgent data processing) do not
have to run immediately. They can run in a later time window or in a different eligible region
where the electricity grid is cleaner. CarbonShift AI helps an operator decide **when and where**
a flexible workload should run so that estimated carbon emissions drop while deadlines and
operational commitments are still met.

Hard rule: never delay an urgent or ineligible workload just to improve its carbon score. All
hard constraints (deadline feasibility, capacity, region eligibility, flexibility) are enforced
in deterministic code *before* any option is shown to the decision model.

## The one decision handed to Strands Decider 2B

After the scheduling engine has produced the **feasible** candidate set (hard constraints already
applied), Strands Decider 2B is asked a single `choice` question: **which feasible candidate best
balances carbon savings against urgency and operational risk?**

This is a judgement, not arithmetic. Picking the literal minimum-emissions candidate is an
`if`/`min()` in code and is never handed to the model. The model weighs prose trade-offs —
deadline slack, how much delay a candidate adds, the workload's priority, how much carbon each
option actually saves — the kind of call reasonable operators disagree on.

## User stories (EARS)

### US-1: Schedule a flexible workload
As an operator, I want to run the agent on a flexible workload so it picks a lower-carbon window.

- WHEN an operator asks the agent to schedule a workload, THE agent SHALL profile it, generate
  feasible candidates in code, and THEN ask Strands Decider 2B which candidate best balances
  carbon against urgency, BEFORE presenting a selected schedule.
- WHEN the scheduling engine finds more than one feasible candidate, THE agent SHALL pass every
  feasible candidate (and only feasible candidates) to Strands Decider 2B as the option set.
- THE agent SHALL pair Strands Decider 2B with Amazon Bedrock: Bedrock drives the conversation
  and the plain-language explanation; Strands Decider 2B makes the candidate choice.

### US-2: Enforce hard constraints before the decision
As an operator, I want unsafe options eliminated before the model sees them.

- WHEN a candidate would miss the workload's deadline, exceed available capacity, or use an
  ineligible region, THE scheduling engine SHALL exclude it from the feasible set in code.
- THE agent SHALL record every excluded candidate and the reason it was excluded in the trace.
- WHEN only one candidate is feasible, THE agent SHALL select it without calling the decider and
  SHALL record that no decision was needed.

### US-3: Respect urgency over carbon
As an operator, I want urgent workloads run on time regardless of carbon.

- WHEN a workload is marked urgent or not flexible, THE scheduling engine SHALL mark only the
  immediate-run window as feasible, so carbon reduction cannot delay it.
- WHEN delaying a workload to any cleaner window would violate its deadline, THE scheduling engine
  SHALL exclude those windows, leaving the immediate window as the feasible choice.

### US-4: Low-confidence handling
As an operator, I want the agent to defer to me when the model is unsure.

- WHEN Strands Decider 2B's confidence in its chosen candidate is below the configurable
  threshold (default 0.6), THE agent SHALL fall back to the deterministic safe choice (the
  lowest-emissions feasible candidate) and SHALL flag the decision for operator review.
- WHEN the decision service is unavailable or returns a candidate id not in the option set, THE
  agent SHALL use the same deterministic fallback and SHALL record the fallback reason. It SHALL
  NOT claim a real Decider decision was made.

### US-5: Independent validation
As an operator, I want the chosen schedule re-checked against the hard constraints.

- WHEN Strands Decider 2B returns a chosen candidate, THE agent SHALL independently re-validate it
  against every hard constraint BEFORE presenting it; if it fails, THE agent SHALL use the
  deterministic fallback.

### US-6: Impact estimate against a baseline
As an operator, I want to see the carbon avoided versus running now.

- THE agent SHALL compute estimated energy (kWh = average power kW x runtime h) and estimated
  emissions (kg CO2e = kWh x carbon intensity kg CO2e/kWh) for the baseline (immediate run) and
  for the selected schedule, and SHALL report the absolute and percentage difference.
- THE agent SHALL label all data as synthetic and SHALL NOT claim synthetic data is live data,
  nor that a workload's estimated emissions equal AWS's whole footprint.

### US-7: Decision trace / audit
As a judge, I want to see what happened at each step.

- THE agent SHALL return, per schedule, the feasible candidates, the excluded candidates with
  reasons, the actual Decider choice and its probabilities, the confidence, the decider latency,
  the fallback status, the validated selection, and the estimated impact.

## Out of scope (for this submission)
- A separate React/Vite frontend or FastAPI server: the kit's `demo/` web UI is the console and
  the kit's `HackathonAgent.chat()` is the backend interface.
- Real-time carbon-intensity APIs: the data-provider seam exists (`agent/data/`) so a real source
  can be added later, but the demo uses labelled synthetic data.
