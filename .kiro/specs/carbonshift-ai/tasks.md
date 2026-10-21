# CarbonShift AI — Tasks

- [ ] 1. Synthetic data: `agent/data/workloads.json`, `agent/data/carbon_windows.json`
- [ ] 2. `agent/scheduler.py`: Workload/Candidate, generate_candidates, feasibility filter,
         energy/emissions math, baseline, impact, render_state, safe_choice
- [ ] 3. `agent/decision.py`: REUSABLE PATTERN docstring, PATTERN_TAG=`#tool-selection`,
         QUESTIONS (fixed C1..C5 choice), CarbonShiftDecision.select with confidence/validation/
         fallback, logging; no IS_KIT_EXAMPLE
- [ ] 4. `agent/tools.py`: list_workloads, profile_workload, generate_candidates, estimate_impact
- [ ] 5. `agent/agent.py`: HackathonAgent (NAME="CarbonShift AI"), chat() seam + decisions log
- [ ] 6. `agent/AGENT.md`, `agent/demo_script.yaml`, `agent/features.yaml`
- [ ] 7. `agent/eval_cases.jsonl`: 24+ labelled choice cases, ~half test, 3 scenarios + near-misses
- [ ] 8. `tests/test_carbonshift.py` with FakeDecider; `./kit test` and `./kit run` green
- [ ] 9. `./kit bench --split tune`, tune if needed, `./kit bench --split test`
