"""Generate notebooks/carbonshift_ai.ipynb: a runnable walkthrough of the CarbonShift AI
decision pattern and benchmark.

The notebook is the kit's existing code, driven cell by cell, so a judge (or a teammate) can run
the carbon-aware scheduling decision, see the preferred-vs-final distinction and the fallback, and
load the real benchmark result, without cloning and wiring anything up. It runs offline with a
FakeDecider, and has an optional live cell that calls the real Strands Decider 2B if a key is set.

    .venv/bin/python scripts/gen_notebook.py

Writes a plain .ipynb (JSON, nbformat 4) with no third-party build dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notebooks" / "carbonshift_ai.ipynb"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": _src(lines)}


def _src(lines) -> list[str]:
    text = "\n".join(lines)
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


CELLS = [
    md(
        "# CarbonShift AI: the Strands Decider 2B decision, end to end",
        "",
        "**Schedule Smarter. Compute Cleaner.** - by Koodal AI Labs",
        "",
        "This notebook is a runnable tour of the decision at the heart of [CarbonShift AI](https://github.com/vjraghavanv/carbonshift-ai),",
        "an agent that decides *when* and *where* a flexible cloud workload should run to cut estimated",
        "carbon while meeting its deadline. It pairs **Amazon Bedrock** (the conversation and the",
        "explanation) with **Strands Decider 2B** (one bounded `choice`: which feasible schedule is best).",
        "",
        "Pattern: `#tool-selection`. What you will do here:",
        "",
        "1. Load a workload and see the deterministic scheduler enforce the hard constraints.",
        "2. See the feasible candidates, each with real energy and emissions numbers.",
        "3. Run the decision with a `FakeDecider` (offline) and read the full record.",
        "4. See the low-confidence **fallback** and the **preferred vs final** distinction.",
        "5. Optionally call the **real** Strands Decider 2B.",
        "6. Load the real **benchmark** result (decider vs an LLM baseline).",
        "",
        "> All data in this project is synthetic and labelled as such. Estimated emissions cover a",
        "> workload's operational electricity only; they are not AWS's whole footprint.",
    ),
    md("## 0. Setup", "", "Run from the repo root so `agent/` and `decider_kit/` import. No extra installs are needed for the offline cells."),
    code(
        "import sys, os, json",
        "from pathlib import Path",
        "",
        "# make the repo root importable whether the notebook runs from notebooks/ or the root",
        "ROOT = Path.cwd()",
        "if (ROOT / 'notebooks').exists() is False and (ROOT.parent / 'agent').exists():",
        "    ROOT = ROOT.parent",
        "sys.path.insert(0, str(ROOT))",
        "sys.path.insert(0, str(ROOT / 'tests'))  # for the offline FakeDecider",
        "print('repo root:', ROOT)",
    ),
    md(
        "## 1. The scheduler: hard constraints in code, not in a model",
        "",
        "The scheduler generates every region-and-time candidate for a workload, then filters out any",
        "that break a hard rule (deadline, capacity, region eligibility, flexibility, and a",
        "priority-based deadline margin). Urgent jobs are reduced to 'run now' here, in code. The",
        "decider never sees an illegal option, and never does arithmetic.",
    ),
    code(
        "from agent import scheduler",
        "",
        "w = scheduler.get_workload('W-ANALYTICS-01')",
        "print(w.name, '|', w.type, '| priority', w.priority, '| deadline', w.deadline_hours, 'h',",
        "      '| runtime', w.runtime_hours, 'h | power', w.avg_power_kw, 'kW | energy', w.energy_kwh, 'kWh')",
    ),
    md("Generate the candidates and show which were excluded and why (the audit trail):"),
    code(
        "all_c = scheduler.all_candidates(w)",
        "feasible = scheduler.feasible(w)",
        "print(f'{len(all_c)} raw candidates -> {len(feasible)} feasible after hard constraints\\n')",
        "for e in scheduler.excluded(w, all_c)[:6]:",
        "    print('EXCLUDED', e['region'], f\"+{e['start_offset_hours']}h\", '->', e['reason'])",
    ),
    md("## 2. The feasible candidates (the exact state handed to the decider)", "", "This text is what Strands Decider 2B reads. Every number is computed in code."),
    code(
        "print(scheduler.render_state(w, feasible))",
    ),
    md(
        "## 3. The decision, offline with a FakeDecider",
        "",
        "`CarbonShiftDecision.select()` is the reusable pattern. We drive it with a `FakeDecider` so this",
        "cell runs with no network and no key. We tell the fake to prefer the lowest-emissions candidate",
        "(what a confident decider typically does here).",
    ),
    code(
        "from fakes import FakeDecider",
        "from agent.decision import CarbonShiftDecision, PATTERN_TAG, CONFIDENCE_THRESHOLD",
        "",
        "print('pattern tag:', PATTERN_TAG, '| confidence threshold:', CONFIDENCE_THRESHOLD)",
        "",
        "safe = scheduler.safe_choice(feasible)        # the lowest-emissions feasible candidate",
        "fake = FakeDecider(lambda state, name, q: safe.cid)   # prefer that candidate, high confidence",
        "sel = CarbonShiftDecision(fake).select(w, feasible)",
        "",
        "print('verdict:', sel.verdict)",
        "print('decider preferred:', sel.chosen_id, '| application final:', sel.candidate.cid)",
        "print('confidence:', round(sel.confidence, 3), '| used_fallback:', sel.used_fallback,",
        "      '| validated:', sel.validated)",
        "print('reason:', sel.reason)",
    ),
    md("The full record the app logs (and the dashboard renders) - note the separate `decider_preferred_id` and `final_selected_id`:"),
    code(
        "rec = CarbonShiftDecision(fake).log if False else None",
        "d = CarbonShiftDecision(fake)",
        "d.select(w, feasible)",
        "print(json.dumps(d.log[-1], indent=1))",
    ),
    md(
        "## 4. Honest uncertainty: the low-confidence fallback",
        "",
        "When the decider's confidence is below the 0.6 operating threshold, the app does **not** trust",
        "the model alone. It falls back to the deterministic lowest-emissions candidate and flags the",
        "schedule for operator review. Here we force the decider to prefer a *non*-fallback candidate at",
        "low confidence, so you can see the preferred candidate differ from the final one.",
    ),
    code(
        "from decider_kit.client import Decision",
        "",
        "preferred = next(c for c in feasible if c.cid != safe.cid)   # NOT the lowest-emissions option",
        "",
        "class LowConf(FakeDecider):",
        "    def ask(self, state, questions, images=None):",
        "        return {'best_candidate': Decision(kind='choice', raw={}, label=preferred.cid,",
        "                                           probabilities={preferred.cid: 0.4}, confidence=0.4)}",
        "",
        "sel = CarbonShiftDecision(LowConf()).select(w, feasible)",
        "print('verdict:', sel.verdict)",
        "print('decider preferred:', sel.chosen_id, f'({preferred.emissions_kg} kgCO2e)')",
        "print('application final:', sel.candidate.cid, f'({sel.candidate.emissions_kg} kgCO2e, the safe fallback)')",
        "print('preferred_differs_from_final:', sel.preferred_differs)",
        "print('needs_review:', sel.needs_review, '| validated:', sel.validated)",
        "print('reason:', sel.reason)",
    ),
    md(
        "This is the key safety property: a low-confidence or invalid model answer can never put an",
        "illegal or worse-than-safe schedule into production. The model classifies; the code acts; the",
        "final choice is independently re-validated.",
    ),
    md(
        "## 5. (Optional) the real Strands Decider 2B",
        "",
        "If you have a decider endpoint configured in `.env` (`DECIDER_MODE`, `DECIDER_URL`,",
        "`DECIDER_API_KEY`) this cell calls the real model. It is safe to skip; the cell catches errors",
        "so the notebook still runs top to bottom without a key.",
    ),
    code(
        "try:",
        "    from decider_kit import Decider",
        "    from decider_kit.config import load_dotenv",
        "    load_dotenv(ROOT / '.env')",
        "    real = CarbonShiftDecision(Decider())",
        "    sel = real.select(w, feasible)",
        "    print('verdict:', sel.verdict, '| preferred:', sel.chosen_id, '-> final:', sel.candidate.cid,",
        "          '| confidence:', round(sel.confidence, 3), '| decider_ms:', round(sel.decider_ms))",
        "    print('probabilities:', sel.probabilities)",
        "except Exception as e:",
        "    print('skipped (no reachable decider configured):', type(e).__name__, e)",
    ),
    md(
        "## 6. The measured result",
        "",
        "`./kit bench --split test` writes `submission/bench/results.json`: Strands Decider 2B against an",
        "LLM baseline on the held-out labelled cases. We load and summarise it here (it is a real run;",
        "nothing in this notebook invents numbers).",
    ),
    code(
        "res_path = ROOT / 'submission' / 'bench' / 'results.json'",
        "if res_path.exists():",
        "    res = json.loads(res_path.read_text())",
        "    s = res['summary']; d, l = s['decider'], s.get('llm', {})",
        "    print(f\"split: {res.get('split')} | decider: {res.get('decider_model')} | LLM: {res.get('llm_model')}\\n\")",
        "    print(f\"{'metric':32} {'decider':>12} {'LLM':>12}\")",
        "    print(f\"{'accuracy':32} {d['accuracy']*100:>11.0f}% {l.get('accuracy',0)*100:>11.0f}%\")",
        "    print(f\"{'latency p50 (ms)':32} {d['latency_p50_ms']:>12} {l.get('latency_p50_ms','-'):>12}\")",
        "    print(f\"{'latency p95 (ms)':32} {d['latency_p95_ms']:>12} {l.get('latency_p95_ms','-'):>12}\")",
        "    print(f\"{'cost / 1,000 decisions (USD)':32} {d['usd_per_1k_decisions']:>12} {l.get('usd_per_1k_decisions','-'):>12}\")",
        "else:",
        "    print('No benchmark yet. Run:  ./kit bench --split test')",
    ),
    md("Per-case view: the decider's pick and confidence against the label and the LLM's pick."),
    code(
        "if res_path.exists():",
        "    for i, row in enumerate(res['rows'], 1):",
        "        exp = row['expected']['best_candidate']",
        "        dec = row['decider']['best_candidate']",
        "        llm = (row.get('llm') or {}).get('best_candidate', {})",
        "        ok = 'OK ' if dec['label'] == exp else 'MISS'",
        "        print(f\"#{i:<2} expected {exp}  decider {dec['label']} ({dec['confidence']:.2f}) {ok}  llm {llm.get('label','-')}\")",
    ),
    md(
        "## How to reuse this decision pattern",
        "",
        "The shape is **constrain in code, judge with the decider, validate in code**:",
        "",
        "1. Your code produces a small, bounded set of already-legal options and renders them as prose.",
        "2. You ask one typed `choice` question over stable ids; the detail lives in the state.",
        "3. Your code decides what to do with the answer: accept if confident and re-validated, else fall",
        "   back to a deterministic safe default and flag for review.",
        "",
        "The full, labelled pattern is in [`agent/decision.py`](https://github.com/vjraghavanv/carbonshift-ai/blob/main/agent/decision.py).",
        "",
        "---",
        "",
        "Built with the AWS User Group Madurai Strands Decider hackathon kit.",
    ),
]

NB = {
    "cells": CELLS,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(NB, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
