"""CarbonShift AI scheduling engine: deterministic, testable, no LLM and no decider.

This is where every *fact* and every *hard constraint* lives. It generates candidate execution
windows for a workload, enforces the hard rules in code (deadline, capacity, region eligibility,
flexibility), and computes energy and emissions for each candidate. Strands Decider 2B is only
ever shown the feasible set this module produces (see agent/decision.py); it never sees an option
that breaks a constraint, and it never invents a number.

Emissions model (synthetic data, documented assumptions):
    energy_kwh    = avg_power_kw * runtime_hours
    emissions_kg  = energy_kwh * carbon_intensity_kg_per_kwh
`avg_power_kw` is a per-workload estimate of average electrical draw across its instances. Carbon
intensity is a synthetic per-region, per-time-window value in agent/data/carbon_windows.json.
Scope is the workload's operational electricity only: not embodied carbon, not PUE, and not AWS's
whole footprint. The baseline is the immediate-run candidate in the workload's home region.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from decider_kit.data import load

# A *shifted or moved* window must still leave at least this many hours of slack before the
# deadline to count as feasible. Keeps "cleaner but risky" options out of the feasible set. The
# immediate run in the home region is exempt (it is the baseline, and an urgent job must be able
# to run now). The required margin grows with priority (below): a high-priority workload needs a
# bigger cushion, so thin-margin "greener" options are filtered out in CODE, not left to the
# decider. This is policy ("could an if-statement decide it?" - yes), so it lives here; the
# decider only ever chooses among options that already respect the workload's priority.
SAFETY_MARGIN_HOURS = 1.0

# Minimum deadline margin a shifted/moved option must keep, by priority. Urgent workloads are
# handled separately (they only ever run now). Tunable, in code.
PRIORITY_MARGIN_HOURS = {"low": 1.0, "normal": 1.0, "high": 3.0}

# The feasible set handed to the decider is capped to this many candidates (small, bounded and
# understandable, as the decision pattern needs). `shortlist()` always keeps the immediate home
# run, then the most distinct lower-carbon options. Must match agent/decision.py MAX_CANDIDATES.
MAX_FEASIBLE = 5
# Simulated free compute capacity (kW) per region window. A candidate whose power exceeds this is
# infeasible (capacity constraint). Deliberately generous except where noted.
REGION_CAPACITY_KW = {"ap-south-1": 20.0, "us-east-1": 40.0, "eu-west-1": 30.0, "eu-north-1": 15.0}


@dataclass
class Workload:
    id: str
    name: str
    type: str
    priority: str
    flexible: bool
    deadline_hours: float
    runtime_hours: float
    avg_power_kw: float
    home_region: str
    eligible_regions: list[str]
    note: str = ""

    @property
    def energy_kwh(self) -> float:
        return round(self.avg_power_kw * self.runtime_hours, 4)


@dataclass
class Candidate:
    cid: str  # stable id C1, C2, ... within one feasible set
    region: str
    start_offset_hours: float
    runtime_hours: float
    carbon_intensity: float
    energy_kwh: float
    emissions_kg: float
    is_home: bool
    kind: str  # "run now" | "shift later" | "move region" | "shift + move"

    @property
    def finish_offset_hours(self) -> float:
        return round(self.start_offset_hours + self.runtime_hours, 4)

    def margin_hours(self, deadline_hours: float) -> float:
        return round(deadline_hours - self.finish_offset_hours, 4)


def load_workloads() -> list[Workload]:
    return [Workload(**{k: row[k] for k in Workload.__dataclass_fields__ if k in row}) for row in load("workloads")]


def get_workload(workload_id: str) -> Workload | None:
    wid = workload_id.strip().upper()
    return next((w for w in load_workloads() if w.id.upper() == wid), None)


def _windows_for(region: str) -> list[dict[str, Any]]:
    rows = [r for r in load("carbon_windows") if r["region"] == region]
    return sorted(rows, key=lambda r: r["start_offset_hours"])


def _intensity(region: str, start_offset: float) -> float | None:
    for r in _windows_for(region):
        if abs(r["start_offset_hours"] - start_offset) < 1e-6:
            return float(r["carbon_intensity_kg_per_kwh"])
    return None


def _emissions(w: Workload, intensity: float) -> float:
    return round(w.energy_kwh * intensity, 4)


def _kind(is_home: bool, start_offset: float) -> str:
    shifted, moved = start_offset > 1e-6, not is_home
    if shifted and moved:
        return "shift + move"
    if moved:
        return "move region"
    if shifted:
        return "shift later"
    return "run now"


def all_candidates(w: Workload) -> list[Candidate]:
    """Every region-window combination for the workload, before any constraint is applied."""
    out: list[Candidate] = []
    for region in w.eligible_regions:
        is_home = region == w.home_region
        for row in _windows_for(region):
            off = float(row["start_offset_hours"])
            intensity = float(row["carbon_intensity_kg_per_kwh"])
            out.append(Candidate(cid="", region=region, start_offset_hours=off, runtime_hours=w.runtime_hours,
                                 carbon_intensity=intensity, energy_kwh=w.energy_kwh,
                                 emissions_kg=_emissions(w, intensity), is_home=is_home, kind=_kind(is_home, off)))
    return out


def _capacity_ok(w: Workload, c: Candidate) -> bool:
    return w.avg_power_kw <= REGION_CAPACITY_KW.get(c.region, float("inf"))


def _is_immediate_home(c: Candidate) -> bool:
    return c.is_home and c.start_offset_hours < 1e-6


def _is_urgent(w: Workload) -> bool:
    return w.priority.lower() == "urgent"


def _required_margin(w: Workload) -> float:
    return PRIORITY_MARGIN_HOURS.get(w.priority.lower(), SAFETY_MARGIN_HOURS)


def _passes(w: Workload, c: Candidate) -> bool:
    # Urgent workloads run now, in the home region, full stop (policy, enforced in code).
    if _is_urgent(w):
        return _is_immediate_home(c) and c.finish_offset_hours <= w.deadline_hours + 1e-6 and _capacity_ok(w, c)
    if c.finish_offset_hours > w.deadline_hours + 1e-6:
        return False
    # shifted/moved options must keep the priority-based margin; the immediate home run is exempt
    if not _is_immediate_home(c) and c.margin_hours(w.deadline_hours) < _required_margin(w) - 1e-6:
        return False
    if not _capacity_ok(w, c):
        return False
    if not w.flexible and not _is_immediate_home(c):
        return False
    return True


def excluded(w: Workload, candidates: list[Candidate]) -> list[dict[str, Any]]:
    """Candidates removed by a hard constraint, each with the reason (for the audit trail)."""
    out: list[dict[str, Any]] = []
    margin = _required_margin(w)
    for c in candidates:
        reasons = []
        if _is_urgent(w) and not _is_immediate_home(c):
            reasons.append("workload is urgent: only an immediate run in the home region is allowed")
        if c.finish_offset_hours > w.deadline_hours + 1e-6:
            reasons.append(f"misses deadline (finishes at {c.finish_offset_hours:g} h, deadline {w.deadline_hours:g} h)")
        elif not _is_urgent(w) and not _is_immediate_home(c) and c.margin_hours(w.deadline_hours) < margin - 1e-6:
            reasons.append(f"deadline margin {c.margin_hours(w.deadline_hours):g} h below the {w.priority} "
                           f"required margin {margin:g} h")
        if not _capacity_ok(w, c):
            reasons.append(f"needs {w.avg_power_kw:g} kW, region capacity {REGION_CAPACITY_KW.get(c.region):g} kW")
        if not w.flexible and not _is_immediate_home(c) and not _is_urgent(w):
            reasons.append("workload is not flexible: only immediate run in the home region is allowed")
        if reasons:
            out.append({"region": c.region, "kind": c.kind, "start_offset_hours": c.start_offset_hours,
                        "emissions_kg": c.emissions_kg, "reason": "; ".join(reasons)})
    return out


def _shortlist(w: Workload, cands: list[Candidate]) -> list[Candidate]:
    """Reduce the passing candidates to a small, bounded, distinct set (<= MAX_FEASIBLE).

    Always keep the immediate home run (the baseline) if it passes, then add the lowest-emissions
    options, skipping any that barely differ from one already kept (so the choice stays meaningful).
    """
    if len(cands) <= MAX_FEASIBLE:
        return cands
    immediate = [c for c in cands if _is_immediate_home(c)]
    rest = sorted((c for c in cands if not _is_immediate_home(c)), key=lambda c: (c.emissions_kg, c.start_offset_hours))
    picked: list[Candidate] = list(immediate)
    for c in rest:
        if len(picked) >= MAX_FEASIBLE:
            break
        # skip near-duplicate emissions (within 5%) of something already picked, to keep options distinct
        if any(abs(c.emissions_kg - p.emissions_kg) <= 0.05 * max(c.emissions_kg, p.emissions_kg) for p in picked):
            continue
        picked.append(c)
    # if dedup left us short, top up with the next lowest-emissions options
    for c in rest:
        if len(picked) >= MAX_FEASIBLE:
            break
        if c not in picked:
            picked.append(c)
    return picked


def feasible(w: Workload, candidates: list[Candidate] | None = None) -> list[Candidate]:
    """The small feasible candidate set: passes every hard constraint, de-duplicated, shortlisted,
    assigned stable ids C1..Cn.

    Ordered with the immediate home-region run first (the baseline), then by start time and
    emissions, so C1 is always the "run now" option when it is feasible.
    """
    cands = candidates if candidates is not None else all_candidates(w)
    keep = [c for c in cands if _passes(w, c)]
    # de-dupe identical (region, start) pairs
    seen: set[tuple[str, float]] = set()
    uniq: list[Candidate] = []
    for c in keep:
        key = (c.region, c.start_offset_hours)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    uniq = _shortlist(w, uniq)
    uniq.sort(key=lambda c: (not _is_immediate_home(c), c.start_offset_hours, c.emissions_kg))
    for i, c in enumerate(uniq, 1):
        c.cid = f"C{i}"
    return uniq


def baseline(w: Workload) -> Candidate:
    """The immediate-run candidate in the home region: what happens with no carbon-aware scheduling."""
    intensity = _intensity(w.home_region, 0.0)
    if intensity is None:
        intensity = min((float(r["carbon_intensity_kg_per_kwh"]) for r in _windows_for(w.home_region)), default=0.0)
    return Candidate(cid="BASE", region=w.home_region, start_offset_hours=0.0, runtime_hours=w.runtime_hours,
                     carbon_intensity=intensity, energy_kwh=w.energy_kwh, emissions_kg=_emissions(w, intensity),
                     is_home=True, kind="run now")


def safe_choice(cands: list[Candidate]) -> Candidate:
    """The deterministic fallback: the feasible candidate with the lowest estimated emissions."""
    return min(cands, key=lambda c: (c.emissions_kg, c.start_offset_hours))


def impact(base: Candidate, chosen: Candidate, deadline_hours: float) -> dict[str, Any]:
    """Baseline vs selected: absolute and percentage emissions difference, and deadline compliance."""
    diff = round(base.emissions_kg - chosen.emissions_kg, 4)
    pct = round(diff / base.emissions_kg * 100, 1) if base.emissions_kg > 0 else 0.0
    return {
        "baseline_emissions_kg": base.emissions_kg,
        "selected_emissions_kg": chosen.emissions_kg,
        "emissions_avoided_kg": diff,
        "emissions_avoided_pct": pct,
        "energy_kwh": chosen.energy_kwh,
        "selected_region": chosen.region,
        "selected_start_offset_hours": chosen.start_offset_hours,
        "deadline_hours": deadline_hours,
        "finish_offset_hours": chosen.finish_offset_hours,
        "deadline_margin_hours": chosen.margin_hours(deadline_hours),
        "meets_deadline": chosen.finish_offset_hours <= deadline_hours + 1e-6,
    }


def _candidate_line(w: Workload, c: Candidate) -> str:
    return (f"{c.cid}: {c.kind} | region {c.region} | starts in {c.start_offset_hours:g} h | "
            f"finishes {c.margin_hours(w.deadline_hours):g} h before deadline | "
            f"carbon {c.carbon_intensity:g} kgCO2e/kWh | est {c.emissions_kg:g} kgCO2e")


def render_state(w: Workload, cands: list[Candidate]) -> str:
    """The exact text handed to Strands Decider 2B (and used verbatim in agent/eval_cases.jsonl)."""
    lines = [
        "--- WORKLOAD ---",
        f"id: {w.id}",
        f"name: {w.name}",
        f"type: {w.type}",
        f"priority: {w.priority}",
        f"flexible: {'yes' if w.flexible else 'no'}",
        f"deadline_hours_remaining: {w.deadline_hours:g}",
        f"runtime_hours: {w.runtime_hours:g}",
        f"avg_power_kw: {w.avg_power_kw:g}",
        f"energy_kwh: {w.energy_kwh:g}",
        "",
        "--- FEASIBLE CANDIDATES (hard constraints already enforced) ---",
    ]
    lines += [_candidate_line(w, c) for c in cands]
    lines += [
        "",
        "--- OBJECTIVE ---",
        "Prefer the lowest estimated emissions while keeping a safe deadline margin and respecting",
        "the workload's priority. Avoid options that cut the deadline margin thin for little carbon",
        "gain, especially for high-priority workloads.",
    ]
    return "\n".join(lines)
