# CarbonShift AI

**CarbonShift AI helps a cloud operator decide *when* and *where* a flexible workload**

An agent on AWS that hands one decision to **Strands Decider 2B** and the conversation to **Amazon Bedrock**. Decision pattern: `#tool-selection`. Tags: `#strands-decider-2b` `#tool-selection`.

- Video: https://youtu.be/WnEWH1dJJQ4
- Article: https://builder.aws.com/content/3Kz73pb35EhdHKR6GNfFL95Cmwz/carbonshift-ai-schedule-smarter-compute-cleaner
- Notebook: [`notebooks/carbonshift_ai.ipynb`](notebooks/carbonshift_ai.ipynb) - a runnable tour of the decision pattern, the fallback and the benchmark
- Deployed: Amazon Bedrock AgentCore Runtime, us-east-1

## The project

**Schedule Smarter. Compute Cleaner.** — by Koodal AI Labs

- **Pitch:** CarbonShift AI helps a cloud operator decide *when* and *where* a flexible workload
  should run so that estimated carbon emissions drop while deadlines and operational commitments
  are still met.
- **Who it is for:** platform and SRE teams who run flexible batch, analytics, ETL, reporting and
  ML-training jobs and want to cut the carbon of that compute without missing deadlines.
- **Features:**
  - a workload queue with runtime, power, deadline, priority and flexibility for each job;
  - a deterministic scheduling engine that generates feasible execution windows across eligible
    regions and enforces every hard constraint (deadline, capacity, eligibility, flexibility) in
    code before anything is decided;
  - per-candidate estimated energy (kWh) and emissions (kg CO2e) from a documented model;
  - a carbon-aware candidate choice made by Strands Decider 2B, with a live decision panel in the
    demo UI showing the feasible options, the excluded ones, the chosen candidate, its confidence
    and its latency;
  - low-confidence, invalid-choice and service-failure handling: a deterministic safe fallback
    (lowest-emissions feasible candidate) plus an operator-review flag;
  - an impact comparison against running now (baseline), with absolute and percentage carbon
    avoided and the deadline margin;
  - deployed on Amazon Bedrock AgentCore Runtime.
- **The decision handed to Strands Decider 2B:** among the feasible schedule candidates (hard
  constraints already enforced), which one best balances lower estimated carbon against a safe
  deadline margin and the workload's priority? A `choice` over candidate ids. (`#tool-selection`)
- **Why a decision model:** this is a judgement, not arithmetic. The literal lowest-emissions
  option is a one-line `min()` in code; the real call is the trade-off between carbon saved and
  deadline risk for a given priority, which reasonable operators weigh differently. The decider
  returns a calibrated confidence the code branches on, fast and cheap, on every schedule.
- **Amazon Bedrock:** the operator conversation and the plain-language explanation of the chosen
  schedule, trade-offs and impact (Amazon Nova Pro by default).

**Honesty note:** all workload and carbon-intensity data in `agent/data/` is synthetic and
labelled as such. Estimated emissions cover the workload's operational electricity only (energy x
grid carbon intensity); they are not AWS's whole footprint and not embodied or PUE-adjusted carbon.
The data-provider seam in `agent/data/` lets a real carbon-intensity source be added later.



## How it is built

Strands Agents with Amazon Bedrock for the generative part, the tools in `agent/tools.py`, deployed to Amazon Bedrock AgentCore Runtime, and one decision handed to Strands Decider 2B at a clear seam in the agent's path.

Every Amazon Bedrock model id is set in `.env` (`BEDROCK_MODEL_ID`, and `BEDROCK_SMALL/MEDIUM/LARGE_MODEL_ID` for routing), Amazon Nova by default.



## Reusable decision pattern: carbon-aware schedule selection  (#tool-selection)

The pattern lives in [`agent/decision.py`](agent/decision.py), labelled `REUSABLE DECISION PATTERN`. It contains the typed questions and their options, the wiring that puts the decision in the agent's path, and a note on how to reuse it:

```text
REUSABLE DECISION PATTERN: carbon-aware schedule selection  (#tool-selection)

What it does
    A deterministic scheduler produces a small, bounded set of *feasible* execution candidates for
    a flexible workload (hard constraints - deadline, capacity, region eligibility, flexibility -
    are already enforced in code; see agent/scheduler.py). Strands Decider 2B then answers one
    `choice` question: which feasible candidate best balances lower estimated carbon emissions
    against a safe deadline margin and the workload's priority?

    This is a judgement, not arithmetic. Picking the literal minimum-emissions candidate is a
    one-line `min()` and is never handed to the model. The model weighs the prose trade-off -
    how much carbon each option really saves, how thin it cuts the deadline margin, how urgent the
    workload is - the kind of call reasonable operators disagree on. Facts (per-candidate energy
    and emissions) are computed in code and written into the state; the model never invents them.

Typed questions and options
    best_candidate (choice): options are stable candidate ids C1..C5. The *meaning* of each id is
    generic ("the candidate shown as C1 in the state", ...) because the real per-candidate detail
    (window, region, deadline margin, estimated emissions) lives in the state text, which both the
    decider and the benchmark's LLM baseline read. The feasible set is ordered so C1 is always the
    immediate "run now" option when it is feasible.

Wiring (where it sits in the agent's path)
    `CarbonShiftDecision.select(workload, feasible)` runs OUTSIDE the Strands tool loop, after the
    scheduler builds the feasible set and before the agent explains the result:

        feasible = scheduler.feasible(workload)
        selection = CarbonShiftDecision(decider).select(workload, feasible)
        # selection.candidate is validated; selection.verdict records how it was chosen

    It records one entry per decider call on `self.log` (probabilities, verdict, decider_ms),
    which agent/agent.py surfaces in chat()["decisions"].

Made once or made often
    This decision is made on every schedule request, and a fleet schedules thousands of flexible
    jobs a day, so it is a high-frequency decision - exactly where the decider's speed and cost
    advantage over an LLM compounds (see submission/bench: same accuracy, ~4-5x faster, a fixed
    fraction of a cent per 1,000 decisions). The same pattern also works for a one-off choice.

How to reuse it (the shape, in any domain)
    The pattern is "constrain in code, judge with the decider, validate in code". To reuse it for
    a different bounded choice (which vendor, which cache tier, which retry region, ...):

        from decider_kit import Decider
        # 1. your code produces a SMALL, bounded set of already-legal options, each rendered as
        #    one line of prose with the facts the judgement needs (never the answer itself):
        options = my_engine.feasible(request)                 # hard rules enforced here, in code
        state = render(options)                               # the facts, as text
        # 2. one typed choice question over stable ids, detail lives in the state:
        q = {"best": Decider.choice("Which option best balances <your trade-off>?",
                                    {o.id: f"the option shown as {o.id}" for o in options})}
        ans = Decider().ask(state, q)["best"]
        # 3. your code decides what to DO with the answer (thresholds you own):
        chosen = by_id.get(ans.label)
        final  = chosen if (chosen and ans.confidence >= THRESHOLD and revalidate(chosen))                  else safe_default(options)                   # fallback + flag for review

    Keep the three invariants: (a) hard constraints and all arithmetic in code, never in the
    model; (b) the decider classifies, your code acts; (c) the final choice is independently
    re-validated and the model can never override a hard constraint. `CarbonShiftDecision` below
    is this shape with carbon scheduling filled in; `select()` holds the thresholds you would tune.
```

Typed questions:

```python
QUESTIONS = {
    "best_candidate": Decider.choice(
        "From the feasible candidates listed in the state, which one is the best schedule for this "
        "workload? Prefer the lowest estimated carbon emissions while keeping a safe deadline "
        "margin and respecting the workload's priority. Do not pick an option that cuts the "
        "deadline margin thin for only a small carbon saving, especially for a high-priority "
        "workload.",
        {cid: f"choose the candidate shown as {cid} in the FEASIBLE CANDIDATES list" for cid in CANDIDATE_IDS},
    ),
}
```

## Measured

Decider: strands-decider-2b-hobson-v19 (ugmdu). 13 labelled cases, 13 decisions.

| | Strands Decider 2B | qwen3.5-4b |
|---|---|---|
| Accuracy | 100.0% | 100.0% |
| Latency p50 per decision | 3278 ms | 4906 ms |
| Latency p95 | 3752 ms | 14709 ms |
| Cost per 1,000 decisions | $0.0350 | $0.0000 |
| Answered alone at confidence >= 0.7 | 8% | 100% |
| Accuracy when confident | 100.0% | 100.0% |

At the median the decider was 1.5x faster than the LLM.

Reproduce with `./kit bench` (cases in `agent/eval_cases.jsonl`; charts in `submission/bench/`).

## Run it

```bash
./kit setup        # checks your machine and AWS, sets up Strands Decider 2B (local model or hosted API)
./kit demo         # web UI at http://localhost:8501
./kit bench        # the decision vs an Amazon Bedrock LLM
./kit deploy       # Amazon Bedrock AgentCore Runtime
```

Requirements: Python 3.10+, AWS credentials with Amazon Bedrock access, and for deploying, Node 20+ with the AgentCore CLI (`./kit agentcore-cli`).

## Credits

Built with the AWS User Group Madurai Strands Decider hackathon kit (https://github.com/awsugmdu). The kit's reusable library (`decider_kit/`, the demo UI, the video and article tooling, and the Kiro steering, skills and hooks) is the user group's; the agent in `agent/` is mine. Strands Decider: https://github.com/strands-labs/strands-decider (Apache-2.0).

Licence: Apache-2.0 (see LICENSE).
