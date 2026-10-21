"""Generate agent/eval_cases.jsonl for CarbonShift AI.

Each case is a hand-authored feasible candidate set written in the EXACT layout
agent/scheduler.render_state produces (so the benchmark and the live agent see the same text),
plus the candidate id a careful operator picks under the documented objective:

    prefer the lowest estimated emissions while keeping a SAFE deadline margin and respecting the
    workload's priority; do NOT cut the margin thin for a small carbon gain, especially for a
    high-priority workload.

We construct the emissions in code (energy x intensity) so every number is real, and we keep the
labels unambiguous (clear winners or clear "keep the margin" calls), rewriting any case that is a
coin-flip. Run:  .venv/bin/python scripts/gen_eval_cases.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "agent" / "eval_cases.jsonl"

# safety margin used by the scheduler; shifted/moved options below it would be infeasible, so every
# candidate we list here already sits at or above it.
SAFETY = 1.0


@dataclass
class Cand:
    kind: str
    region: str
    start: float
    carbon: float
    runtime: float
    power: float

    def energy(self) -> float:
        return round(self.power * self.runtime, 4)

    def emissions(self) -> float:
        return round(self.energy() * self.carbon, 4)

    def finish(self) -> float:
        return round(self.start + self.runtime, 4)

    def margin(self, deadline: float) -> float:
        return round(deadline - self.finish(), 4)


def _g(x: float) -> str:
    return f"{x:g}"


def render(wl: dict, cands: list[Cand]) -> str:
    runtime, power = wl["runtime_hours"], wl["avg_power_kw"]
    energy = round(power * runtime, 4)
    lines = [
        "--- WORKLOAD ---",
        f"id: {wl['id']}",
        f"name: {wl['name']}",
        f"type: {wl['type']}",
        f"priority: {wl['priority']}",
        f"flexible: {'yes' if wl['flexible'] else 'no'}",
        f"deadline_hours_remaining: {_g(wl['deadline_hours'])}",
        f"runtime_hours: {_g(runtime)}",
        f"avg_power_kw: {_g(power)}",
        f"energy_kwh: {_g(energy)}",
        "",
        "--- FEASIBLE CANDIDATES (hard constraints already enforced) ---",
    ]
    for i, c in enumerate(cands, 1):
        lines.append(
            f"C{i}: {c.kind} | region {c.region} | starts in {_g(c.start)} h | "
            f"finishes {_g(c.margin(wl['deadline_hours']))} h before deadline | "
            f"carbon {_g(c.carbon)} kgCO2e/kWh | est {_g(c.emissions())} kgCO2e"
        )
    lines += [
        "",
        "--- OBJECTIVE ---",
        "Prefer the lowest estimated emissions while keeping a safe deadline margin and respecting",
        "the workload's priority. Avoid options that cut the deadline margin thin for little carbon",
        "gain, especially for high-priority workloads.",
    ]
    return "\n".join(lines)


def case(wl: dict, cands: list[Cand], expected: str, split: str) -> dict:
    return {"state": render(wl, cands), "expected": {"best_candidate": expected}, "split": split}


def wl(id, name, type, priority, flexible, deadline, runtime, power):
    return {"id": id, "name": name, "type": type, "priority": priority, "flexible": flexible,
            "deadline_hours": deadline, "runtime_hours": runtime, "avg_power_kw": power}


CASES: list[dict] = []
A = CASES.append

# ---------------------------------------------------------------------------------------------
# SCENARIO 1: flexible analytics with slack -> the clearly cleaner option wins (comfortable margin)
# ---------------------------------------------------------------------------------------------
w1 = wl("W-ANALYTICS-01", "Nightly revenue rollup", "analytics", "normal", True, 14, 2, 3.5)
A(case(w1, [Cand("run now", "ap-south-1", 0, 0.71, 2, 3.5),
            Cand("shift + move", "eu-west-1", 4, 0.23, 2, 3.5),
            Cand("shift + move", "eu-west-1", 6, 0.19, 2, 3.5),
            Cand("shift + move", "us-east-1", 6, 0.30, 2, 3.5),
            Cand("shift + move", "eu-west-1", 10, 0.27, 2, 3.5)], "C3", "tune"))  # 1.33, 6h margin

w1b = wl("W-ANALYTICS-07", "Ad impressions rollup", "analytics", "normal", True, 12, 2, 4.0)
A(case(w1b, [Cand("run now", "ap-south-1", 0, 0.68, 2, 4.0),
             Cand("move region", "us-east-1", 0, 0.40, 2, 4.0),
             Cand("shift + move", "eu-north-1", 4, 0.09, 2, 4.0),
             Cand("shift later", "ap-south-1", 6, 0.52, 2, 4.0)], "C3", "test"))  # 0.72, 6h margin, cleanest & safe

w1c = wl("W-ANALYTICS-08", "Session log aggregation", "analytics", "low", True, 18, 1.5, 3.0)
A(case(w1c, [Cand("run now", "us-east-1", 0, 0.42, 1.5, 3.0),
             Cand("move region", "eu-west-1", 0, 0.33, 1.5, 3.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 1.5, 3.0),
             Cand("shift + move", "eu-north-1", 10, 0.08, 1.5, 3.0)], "C3", "tune"))  # 0.225, huge margin

# ---------------------------------------------------------------------------------------------
# SCENARIO 2: deadline-constrained -> cleanest option that keeps a SAFE margin wins, not the
#             greenest-but-thin one (near-misses: greenest cuts margin to the bone for little gain)
# ---------------------------------------------------------------------------------------------
w2 = wl("W-ETL-02", "Customer data ETL", "data-processing", "normal", True, 8, 3, 5.0)
# C4 greenest (3.45) at 1h margin vs C2 (4.95) at 5h; for NORMAL priority the bigger carbon win is
# worth the still-legal 1h margin -> C4.
A(case(w2, [Cand("run now", "us-east-1", 0, 0.42, 3, 5.0),
            Cand("move region", "eu-west-1", 0, 0.33, 3, 5.0),
            Cand("shift later", "us-east-1", 3, 0.38, 3, 5.0),
            Cand("shift + move", "eu-west-1", 4, 0.23, 3, 5.0)], "C4", "tune"))

# high priority: the scheduler already removed any option below the 3h high-priority margin, so
# every listed candidate keeps >=3h slack. Among those safe options the cleanest wins -> C3.
w2b = wl("W-ETL-09", "Fraud feature backfill", "data-processing", "high", True, 9, 3, 6.0)
A(case(w2b, [Cand("run now", "us-east-1", 0, 0.42, 3, 6.0),
             Cand("move region", "eu-west-1", 0, 0.30, 3, 6.0),
             Cand("shift + move", "eu-north-1", 2, 0.09, 3, 6.0)], "C3", "test"))
# C1 7.56, C2 5.4, C3 1.62; all keep >=4h margin -> cleanest safe option C3.

# deadline-constrained batch where only two options are feasible and the move-region one is both
# cleaner and keeps the same margin -> clear C2.
w2c = wl("W-BATCH-10", "Invoice PDF batch", "batch", "normal", True, 6, 2, 4.0)
A(case(w2c, [Cand("run now", "us-east-1", 0, 0.42, 2, 4.0),
             Cand("move region", "eu-north-1", 0, 0.12, 2, 4.0)], "C2", "tune"))  # both 4h margin, C2 far cleaner

w2d = wl("W-ETL-11", "Clickstream dedupe", "data-processing", "normal", True, 8, 3, 5.0)
# normal priority, all options keep a legal margin -> cleanest wins (C4).
A(case(w2d, [Cand("run now", "us-east-1", 0, 0.42, 3, 5.0),
             Cand("move region", "eu-west-1", 0, 0.33, 3, 5.0),
             Cand("shift later", "us-east-1", 3, 0.30, 3, 5.0),
             Cand("shift + move", "eu-west-1", 4, 0.23, 3, 5.0)], "C4", "test"))
# C1 6.3, C2 4.95, C3 4.5, C4 3.45 (1h margin, legal for normal) -> cleanest C4.

# ---------------------------------------------------------------------------------------------
# SCENARIO 3: strong region swing -> clean region at a comfortable time wins decisively
# ---------------------------------------------------------------------------------------------
w3 = wl("W-ML-04", "Recommendation model retrain", "ml-training", "normal", True, 20, 6, 12.0)
A(case(w3, [Cand("run now", "eu-west-1", 0, 0.33, 6, 12.0),
            Cand("move region", "eu-north-1", 0, 0.12, 6, 12.0),
            Cand("shift + move", "eu-north-1", 4, 0.09, 6, 12.0),
            Cand("shift + move", "eu-north-1", 6, 0.05, 6, 12.0),
            Cand("shift + move", "eu-north-1", 10, 0.08, 6, 12.0)], "C4", "tune"))  # 3.6, 8h margin

w3b = wl("W-ML-12", "Embeddings refresh", "ml-training", "normal", True, 16, 4, 10.0)
A(case(w3b, [Cand("run now", "eu-west-1", 0, 0.33, 4, 10.0),
             Cand("move region", "eu-north-1", 0, 0.12, 4, 10.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 4, 10.0)], "C3", "test"))  # 2.0, 6h margin, cleanest & safe

w3c = wl("W-ML-13", "Churn model nightly", "ml-training", "low", True, 22, 5, 11.0)
A(case(w3c, [Cand("run now", "us-east-1", 0, 0.42, 5, 11.0),
             Cand("move region", "eu-north-1", 0, 0.12, 5, 11.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 5, 11.0),
             Cand("shift + move", "eu-north-1", 10, 0.08, 5, 11.0)], "C3", "tune"))  # cleanest, big margin

# ---------------------------------------------------------------------------------------------
# SCENARIO 4: high priority with comfortable slack -> all listed options keep the 3h+ margin the
#             scheduler enforces, so the cleanest safe option wins (no thin-margin trap reaches
#             the decider; that is handled in code).
# ---------------------------------------------------------------------------------------------
w4 = wl("W-REPORT-05", "Compliance report generation", "report", "high", True, 6, 2, 2.5)
A(case(w4, [Cand("run now", "eu-west-1", 0, 0.33, 2, 2.5),
            Cand("move region", "eu-north-1", 0, 0.12, 2, 2.5)], "C2", "test"))  # both 4h margin, C2 cleaner

w4b = wl("W-REPORT-14", "Quarterly audit export", "report", "high", True, 9, 3, 3.0)
A(case(w4b, [Cand("run now", "eu-west-1", 0, 0.33, 3, 3.0),
             Cand("move region", "eu-north-1", 0, 0.12, 3, 3.0),
             Cand("shift + move", "eu-north-1", 2, 0.09, 3, 3.0)], "C3", "tune"))
# C1 2.97, C2 1.08, C3 0.81; all keep >=4h margin -> cleanest safe option C3.

w4c = wl("W-REPORT-15", "SLA breach summary", "report", "high", True, 9, 2, 3.0)
A(case(w4c, [Cand("run now", "eu-west-1", 0, 0.33, 2, 3.0),
             Cand("move region", "eu-north-1", 0, 0.12, 2, 3.0),
             Cand("shift + move", "eu-north-1", 2, 0.05, 2, 3.0)], "C3", "test"))  # 0.3, >=5h margin, cleanest

# ---------------------------------------------------------------------------------------------
# SCENARIO 5: normal-priority region swings where the cleanest safe option is a clear win
#             (urgent workloads are decided in code as run-now-only, so they are not decider cases)
# ---------------------------------------------------------------------------------------------
w5 = wl("W-ANALYTICS-16", "Funnel metrics rollup", "analytics", "normal", True, 10, 2, 4.0)
A(case(w5, [Cand("run now", "ap-south-1", 0, 0.71, 2, 4.0),
            Cand("move region", "us-east-1", 0, 0.42, 2, 4.0),
            Cand("shift + move", "eu-north-1", 4, 0.05, 2, 4.0)], "C3", "tune"))  # 0.4, cleanest, 4h margin

w5b = wl("W-ETL-17", "Reference data sync", "data-processing", "low", True, 12, 2, 5.0)
A(case(w5b, [Cand("run now", "us-east-1", 0, 0.42, 2, 5.0),
             Cand("move region", "eu-west-1", 0, 0.33, 2, 5.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 2, 5.0)], "C3", "test"))  # cleanest, big margin

# ---------------------------------------------------------------------------------------------
# SCENARIO 6: near-ties on carbon decided by the larger deadline margin
# ---------------------------------------------------------------------------------------------
w6 = wl("W-BACKUP-06", "Cross-region backup verification", "batch", "low", True, 24, 1.5, 1.8)
A(case(w6, [Cand("run now", "us-east-1", 0, 0.42, 1.5, 1.8),
            Cand("move region", "eu-north-1", 0, 0.12, 1.5, 1.8),
            Cand("shift + move", "eu-north-1", 6, 0.05, 1.5, 1.8),
            Cand("shift + move", "eu-north-1", 10, 0.08, 1.5, 1.8)], "C3", "tune"))  # 0.135, cleanest, huge margin

w6b = wl("W-BACKUP-18", "Snapshot integrity check", "batch", "normal", True, 10, 2, 2.0)
# C2 and C3 both eu-north-1, near-equal carbon (0.09 vs 0.08); C3 same cleanliness class but starts
# later with less margin; C2 is cleaner-enough and keeps more margin -> C2.
A(case(w6b, [Cand("run now", "us-east-1", 0, 0.42, 2, 2.0),
             Cand("shift + move", "eu-north-1", 4, 0.09, 2, 2.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 2, 2.0)], "C3", "test"))
# C1 1.68, C2 0.36 (4h margin), C3 0.20 (2h margin). Low-ish, big carbon win C2->C3, still safe -> C3.

w6c = wl("W-BACKUP-19", "Archive tier migration", "batch", "low", True, 30, 2, 2.0)
A(case(w6c, [Cand("run now", "us-east-1", 0, 0.42, 2, 2.0),
             Cand("move region", "eu-west-1", 0, 0.33, 2, 2.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 2, 2.0),
             Cand("shift + move", "eu-north-1", 10, 0.08, 2, 2.0)], "C3", "tune"))  # cleanest, enormous margin

# ---------------------------------------------------------------------------------------------
# SCENARIO 7: the greenest option would miss the safe margin but is absent (already filtered);
#             among what remains the move-region-now option is both cleaner and safe -> clear.
# ---------------------------------------------------------------------------------------------
w7 = wl("W-ETL-20", "Nightly warehouse load", "data-processing", "normal", True, 5, 2, 4.0)
A(case(w7, [Cand("run now", "us-east-1", 0, 0.42, 2, 4.0),
            Cand("move region", "eu-north-1", 0, 0.12, 2, 4.0),
            Cand("shift later", "us-east-1", 2, 0.30, 2, 4.0)], "C2", "test"))  # C2 cleanest, 3h margin

w7b = wl("W-ANALYTICS-21", "Marketing attribution", "analytics", "normal", True, 9, 2, 3.0)
A(case(w7b, [Cand("run now", "ap-south-1", 0, 0.71, 2, 3.0),
             Cand("move region", "eu-west-1", 0, 0.33, 2, 3.0),
             Cand("shift + move", "eu-north-1", 4, 0.09, 2, 3.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 2, 3.0)], "C4", "tune"))  # 0.3, 1h margin ok for normal, far cleanest

w7c = wl("W-REPORT-22", "Weekly KPI deck", "report", "normal", True, 7, 1.5, 2.0)
A(case(w7c, [Cand("run now", "eu-west-1", 0, 0.33, 1.5, 2.0),
             Cand("move region", "eu-north-1", 0, 0.12, 1.5, 2.0),
             Cand("shift + move", "eu-north-1", 4, 0.05, 1.5, 2.0)], "C3", "test"))  # 0.15, safe margin, cleanest

# ---------------------------------------------------------------------------------------------
# SCENARIO 8: more coverage to reach 24+ cases (12+ per split), varied priorities and swings
# ---------------------------------------------------------------------------------------------
w8 = wl("W-ANALYTICS-23", "Cohort retention rollup", "analytics", "normal", True, 15, 2, 4.0)
A(case(w8, [Cand("run now", "ap-south-1", 0, 0.71, 2, 4.0),
            Cand("move region", "eu-west-1", 0, 0.33, 2, 4.0),
            Cand("shift + move", "eu-north-1", 6, 0.05, 2, 4.0),
            Cand("shift + move", "eu-north-1", 10, 0.08, 2, 4.0)], "C3", "test"))  # 0.4, 7h margin, cleanest

w8b = wl("W-ML-24", "Vision model finetune", "ml-training", "normal", True, 18, 5, 12.0)
A(case(w8b, [Cand("run now", "eu-west-1", 0, 0.33, 5, 12.0),
             Cand("move region", "eu-north-1", 0, 0.12, 5, 12.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 5, 12.0)], "C3", "test"))  # 3.0, 7h margin, cleanest

w8c = wl("W-BATCH-25", "Daily ledger archive", "batch", "normal", True, 9, 1, 3.0)
A(case(w8c, [Cand("run now", "us-east-1", 0, 0.42, 1, 3.0),
             Cand("move region", "eu-west-1", 0, 0.33, 1, 3.0),
             Cand("shift + move", "eu-north-1", 4, 0.05, 1, 3.0)], "C3", "test"))  # 0.15, cleanest, 4h margin

w8d = wl("W-ETL-26", "Supplier feed import", "data-processing", "normal", True, 11, 2, 5.0)
A(case(w8d, [Cand("run now", "us-east-1", 0, 0.42, 2, 5.0),
             Cand("move region", "eu-west-1", 0, 0.33, 2, 5.0),
             Cand("shift + move", "eu-north-1", 6, 0.05, 2, 5.0)], "C3", "tune"))  # 0.5, 3h margin, cleanest


def main() -> None:
    OUT.write_text("".join(json.dumps(c) + "\n" for c in CASES))
    n_tune = sum(1 for c in CASES if c["split"] == "tune")
    n_test = sum(1 for c in CASES if c["split"] == "test")
    print(f"wrote {len(CASES)} cases to {OUT.relative_to(ROOT)}  (tune={n_tune}, test={n_test})")


if __name__ == "__main__":
    main()
