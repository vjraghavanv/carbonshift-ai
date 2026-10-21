# CarbonShift AI: a carbon-aware scheduling agent that lets Strands Decider 2B pick when and where cloud jobs run

By Koodal AI Labs

A lot of cloud work does not have to run the instant it is queued. Nightly rollups, ETL, report generation, model retraining: these can slide a few hours, or move to a region whose grid is cleaner right now, and still finish comfortably before their deadline. CarbonShift AI is an agent that makes that call. It reads a workload, works out the legal ways to run it, and hands Strands Decider 2B one bounded question: of these feasible options, which best trades lower carbon against a safe deadline margin and the job's priority? On a held-out test set the decider matched an Amazon Bedrock LLM on accuracy, 100 percent to 100 percent, while answering in a steady 3.3 seconds against the LLM's 4.9 second median and 14.7 second tail. Same answers, far more predictable, for a fraction of a cent per thousand decisions.

## The project

CarbonShift AI is for platform and SRE teams who run flexible batch, analytics, ETL, reporting and training jobs and want to cut the carbon of that compute without missing a deadline or breaking a commitment.

What it does, as a product:

- keeps a queue of workloads, each with its runtime, average power, deadline, priority and whether it is flexible;
- generates feasible execution candidates across eligible regions and time windows, and enforces every hard constraint (deadline, capacity, region eligibility, flexibility) in plain code before anything is decided;
- estimates energy (kWh) and emissions (kg CO2e) per candidate from a documented model;
- hands the final trade-off to Strands Decider 2B, and shows the whole decision live: every candidate, the one the decider preferred, the one the application actually scheduled, the confidence and the probabilities;
- falls back to a deterministic safe choice and raises an operator-review flag when confidence is low;
- compares the chosen schedule against running now, in absolute and percentage carbon avoided.

Here is a real turn against the deployed agent. The operator types "Schedule W-ANALYTICS-01 for the lowest carbon while meeting its deadline." The agent produces five feasible candidates, the decider prefers candidate C3 (shift the job six hours and run it in eu-west-1) at confidence 0.68, the application re-validates that choice and accepts it, and Amazon Bedrock explains the result: run in eu-west-1 starting in six hours, avoiding an estimated 3.64 kg CO2e versus running now, finishing six hours before the deadline. A second turn schedules a high-priority report (W-REPORT-05); the decider picks the cleaner region that still keeps a safe margin, at confidence 0.75. A third asks for the urgent billing reconciliation (W-BILLING-03); only one option is feasible, so the agent runs it now and never calls the decider. Carbon never delays an urgent job.

< FIGURE 1 of 6: upload submission/article/img/demo.png here >
Alt text: The demo UI: the conversation on the left, the decider's typed answers and verdict on the right

## How I built it

CarbonShift AI is a Strands Agents app. Amazon Bedrock (Amazon Nova Pro on the deployed runtime) runs the conversation and writes the plain-language explanation. The tools (list the queue, profile a workload, generate candidates, estimate impact) are ordinary Strands tools over a deterministic scheduling engine. That engine is where every number and every hard constraint lives; the agent never asks a model to do arithmetic. Strands Decider 2B sits at one seam, between "here are the legal options" and "here is the schedule we will run." The whole thing is deployed to Amazon Bedrock AgentCore Runtime, which is what the demo video records. I built it spec-first in Kiro: a requirements, design and tasks document drove the scheduler, the decision pattern and the eval cases before any of it was wired together.

< FIGURE 2 of 6: upload submission/article/img/architecture.png here >
Alt text: Architecture: the user, the agent with its tools and decision, Amazon Bedrock and Strands Decider 2B

## The decision I handed to Strands Decider 2B

The temptation is to let an LLM "just pick the greenest schedule." But the literal lowest-emissions option is a one-line min() over the candidates, and computing it in code is reliable and free. That is not the decision worth a model. The real decision is a judgement that reasonable operators disagree on: how much carbon is a given saving worth if it shaves the deadline margin thinner, and how does that change when the job is high priority? That is about reading a trade-off, not doing a sum, which is exactly what a calibrated decision model is for.

So the scheduler produces a small, bounded set of already-feasible candidates and writes them into a state as prose, with each candidate's window, region, deadline margin and estimated emissions. The decider answers one typed choice question:

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

The options are stable candidate ids (C1..C5); the real detail lives in the state, which both the decider and the LLM baseline read. My code then decides what to do with the answer. If confidence is at or above 0.6 and the preferred candidate passes an independent re-validation against the hard constraints, the application runs it; otherwise it falls back to the deterministic lowest-emissions candidate and flags the schedule for operator review. The model classifies, the code acts, and the final choice is always re-validated, so the model can never override a hard constraint. The agent records the decider's preferred candidate separately from the one it finally scheduled, so you can see whether a fallback changed the outcome.

## Measured

I benchmarked the decider against the same typed question answered by an Amazon Bedrock style LLM (qwen3.5-4b through the AWS User Group Madurai cloud), on a held-out test split of 13 labelled cases I did not tune on. The decider ran on the hosted Strands Decider 2B API.

Decider: strands-decider-2b-hobson-v19 (ugmdu). 13 labelled cases, 13 decisions.

| | Strands Decider 2B | qwen3.5-4b |
|---|---|---|
| Accuracy | 100.0% | 100.0% |
| Latency p50 per decision | 3278 ms | 4906 ms |
| Latency p95 | 3752 ms | 14709 ms |
| Cost per 1,000 decisions | $0.0350 | $0.0000 |
| Answered alone at confidence >= 0.7 | 8% | 100% |
| Accuracy when confident | 100.0% | 100.0% |

Two honest points. First, latency: the LLM's median was not far off the decider's, but its tail was long and load-dependent (a p95 of 14.7 seconds against the decider's steady 3.8), so across runs the median speedup swung between about 1.5x and 4.7x. The decider's real win here is not a single big number, it is consistency and cost. Second, confidence: the decider only cleared a 0.7 bar on about 8 percent of cases, yet it was correct on all 13. That is not a flaw. These are close trade-offs, so the probability mass splits across several good candidates and the top pick sits near 0.5. The agent's operating threshold is 0.6, and below it the application does not trust the model alone; it uses the deterministic fallback and asks for review. So a low-confidence call still lands on a safe, correct schedule, and you can watch it happen in the demo.

< FIGURE 3 of 6: upload submission/article/img/bench-accuracy.png here >
Alt text: Accuracy of Strands Decider 2B and the Bedrock LLM on the labelled cases

< FIGURE 4 of 6: upload submission/article/img/bench-latency.png here >
Alt text: Median latency per decision for both

< FIGURE 5 of 6: upload submission/article/img/bench-cost.png here >
Alt text: Cost per 1,000 decisions for both

< FIGURE 6 of 6: upload submission/article/img/bench-confidence.png here >
Alt text: Accuracy against the share of decisions answered without a human, as the confidence threshold moves

## The reusable decision pattern

The pattern lives in agent/decision.py, labelled REUSABLE DECISION PATTERN, and its shape is "constrain in code, judge with the decider, validate in code." It is a tool-selection pattern (tag #tool-selection): the agent selects one option from a bounded set. Dropping it into a different agent means three steps. Your code produces a small set of already-legal options and renders them as prose with the facts the judgement needs. You ask one typed choice question over stable ids, with the detail in the state. Then your code decides what to do with the answer, keeping the thresholds you own: accept if confident and re-validated, otherwise fall back and flag. Swap carbon scheduling for your own domain (which vendor, which cache tier, which retry region) and the rest carries over. The pattern keeps three invariants: all arithmetic and hard constraints in code, the decider classifies while your code acts, and the final choice is independently re-validated so the model can never break a hard rule. It is a made-over-and-over decision: a fleet schedules thousands of flexible jobs a day, and that is where the decider's speed and cost edge compounds.

## What I learned and what is next

The biggest lesson was where to draw the line between code and model. My first version let the decider handle urgency and the high-priority margin too, and both the decider and the LLM got those cases wrong, because "an urgent job runs now" is a policy an if-statement decides reliably, not a judgement. Moving that rule into the scheduler lifted accuracy to 100 percent and left the decider a coherent job: the genuine carbon-versus-margin trade-off. I also learned that narrow questions win. A longer, multi-clause version of the question dropped tune accuracy from 92 percent to 17 percent; the short version restored it. And I came to see modest confidence as a feature: the decider is honestly uncertain on close calls, and the fallback turns that honesty into a safe default plus a review flag. Next steps are a real carbon-intensity data source behind the existing provider seam, and cross-region capacity signals so the candidate set reflects live headroom.

All data in this project is synthetic and labelled as such. Estimated emissions cover a workload's operational electricity only; they are not AWS's whole footprint, and not embodied or PUE-adjusted carbon.

---

Code: https://github.com/vjraghavanv/carbonshift-ai . Video: [paste the public YouTube or Vimeo link after upload] . Tags: #strands-decider-2b #tool-selection

Built with the AWS User Group Madurai Strands Decider hackathon kit
