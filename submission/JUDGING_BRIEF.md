# CarbonShift AI — how it maps to the judging criteria

A working brief for the article and video. Every number here comes from a real run
(`submission/bench/results.json`, `./kit invoke` against the deployed agent). Nothing invented.

## Declared decision pattern

**Tool selection** (`#tool-selection`) + `#strands-decider-2b`.

The agent hands Strands Decider 2B one bounded `choice`: among the feasible schedule candidates
(each a distinct "run here, at this time" option), **which one** to run. That is a selection among
options, which is the tool-selection shape. It is a **made-over-and-over** decision: every
schedule request triggers it, and a real fleet schedules thousands of flexible jobs a day — the
high-frequency case where the decider's speed and cost advantage compounds.

## Creativity and cool factor (30%)

- A sustainability angle most agents don't touch: **carbon-aware scheduling**. The agent moves a
  cloud job in *time* and *region* to a cleaner grid window, and shows the carbon it avoided.
- The "cool" beat on camera: the live decision panel shows all candidates with their emissions and
  deadline margins, the candidate the decider **preferred**, the candidate the app **finally ran**,
  the confidence, and — when confidence is low — the fallback kicking in and asking for review.
- It demonstrates restraint, which is itself interesting: the agent will **not** chase carbon when
  a job is urgent or a cleaner window would cut the deadline too fine. That rule lives in code.

## Effective use of Decider 2B with Amazon Bedrock (30%)

- **Clean division of labour.** Amazon Bedrock (Nova Pro on the deployed agent) runs the
  conversation and writes the plain-language explanation. Strands Decider 2B makes the one bounded
  judgement. Each does what it is best at.
- **A decision worth a model, not an `if`.** The literal lowest-emissions option is a `min()` and
  is computed in code, never asked. The decider weighs the *trade-off* (carbon saved vs deadline
  margin vs priority) that reasonable operators disagree on — exactly what a decision model is for.
- **Quality of the reusable pattern.** `agent/decision.py` is labelled `REUSABLE DECISION PATTERN`,
  states the three invariants (constrain in code, judge with the decider, validate in code), and
  ships a copyable skeleton for reuse in any bounded-choice domain. Hard constraints, independent
  re-validation, low-confidence fallback and the preferred-vs-final distinction are all explicit.
- **Measured bonus (honest).** Held-out test split, 13 labelled cases, decider vs qwen3.5-4b LLM:
  - Accuracy: **100% vs 100%** (tie on correctness).
  - Latency p50: decider **~3.2 s**, steady (p95 ~3.8 s); the LLM is **~4.9 s p50 but ~14.7 s p95**
    — a long, load-dependent tail. Median speedup ranges **~1.5x to ~4.7x** across runs; the
    decider's real win here is **consistency** (tight p50/p95) and **cost**.
  - Cost: **$0.035 vs variable** per 1,000 decisions on this setup.
  - Low-confidence handling (the honest headline): on the held-out split the decider was correct
    on **13/13** cases while its top-1 confidence sat at a **median ~0.52** (range 0.44-0.73). That
    is not a weakness: these are close trade-offs, so the probability mass splits across several
    good candidates, yet the top pick is right every time. The agent's **operating threshold is
    0.6** - below it, the app does not trust the model alone: it uses the deterministic
    lowest-emissions fallback and flags the schedule for operator review. So a low-confidence call
    still lands on a safe, correct option, visibly.

## Communication quality (25%)

- README leads with the problem, who it's for, the features, the decision, and the measured table.
- The decision is **visible in the product**: a live decision panel (all candidates with emissions
  and margins, the decider's preferred candidate vs the application's final one, confidence,
  probabilities, validation, fallback reason) and a **Benchmark tab** that shows the real held-out
  test cases and the decider-vs-LLM result inside the demo UI - a judge sees the evidence live, not
  just in a report. Screenshots in `submission/screenshots/`.
- Article plan: problem -> architecture (Bedrock + Decider seam) -> the reusable pattern -> the
  measured comparison (with the honest latency-variance caveat) -> what we learned (moving policy
  into code; narrow questions beat verbose ones; calibrated confidence as a feature).
- Video plan (<3 min): the queue, a confident carbon shift, a high-priority "keep the margin" case,
  and a low-confidence fallback with the review flag — each showing the decision panel live.

## Originality (15%)

- Carbon-aware, deadline-respecting workload scheduling as an *agent decision* is an uncommon take;
  most carbon tooling is a dashboard, not an agent that decides and explains.
- The preferred-vs-final distinction (what the model wanted vs what the app safely ran) and the
  "constrain in code, judge with the decider, validate in code" framing are the original contribution
  other builders can lift.

## What we learned (for the article's honesty section)

1. **Put policy in code, judgement in the model.** Urgency and the high-priority deadline margin
   were first left to the decider; both it and the LLM mislabelled those cases. Moving them to the
   scheduler (an `if`) lifted accuracy to 100% and made the decider's remaining job coherent.
2. **Narrow questions win.** A longer, multi-clause objective dropped tune accuracy from 92% to
   17%. Reverting to the simple question restored it. Measured, then reverted.
3. **Calibrated confidence is a feature, not a flaw.** The decider sits at 0.4-0.7 on genuinely
   close trade-offs; the fallback turns that honesty into a safe default plus a review flag.
