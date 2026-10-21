"""CarbonShift AI tools: the agent's view of the workload queue and the scheduling engine.

All data is synthetic and lives in agent/data/ (workloads.json, carbon_windows.json). The
scheduling engine (agent/scheduler.py) does every calculation and enforces every hard constraint;
these tools are thin wrappers so the LLM (Amazon Bedrock) can read the queue, profile a workload,
see the feasible candidates, and report impact. The carbon-aware candidate CHOICE is made by
Strands Decider 2B in agent/decision.py, not here and not by the LLM.
"""

from __future__ import annotations

from strands import tool

from . import scheduler


@tool
def list_workloads() -> list[dict]:
    """List the pending workloads awaiting scheduling, with id, name, type, priority and deadline."""
    return [{"id": w.id, "name": w.name, "type": w.type, "priority": w.priority,
             "flexible": w.flexible, "deadline_hours": w.deadline_hours, "runtime_hours": w.runtime_hours}
            for w in scheduler.load_workloads()]


@tool
def profile_workload(workload_id: str) -> dict:
    """Profile one workload: runtime, power, energy, deadline, priority, flexibility and eligible regions."""
    w = scheduler.get_workload(workload_id)
    if not w:
        return {"error": f"no workload {workload_id}"}
    return {"id": w.id, "name": w.name, "type": w.type, "priority": w.priority, "flexible": w.flexible,
            "deadline_hours": w.deadline_hours, "runtime_hours": w.runtime_hours, "avg_power_kw": w.avg_power_kw,
            "energy_kwh": w.energy_kwh, "home_region": w.home_region, "eligible_regions": w.eligible_regions,
            "note": w.note}


@tool
def generate_candidates(workload_id: str) -> dict:
    """Generate feasible schedule candidates for a workload (hard constraints already enforced),
    plus the options excluded and why. Each candidate has its estimated energy and emissions."""
    w = scheduler.get_workload(workload_id)
    if not w:
        return {"error": f"no workload {workload_id}"}
    all_c = scheduler.all_candidates(w)
    feas = scheduler.feasible(w, all_c)
    return {
        "workload_id": w.id,
        "feasible": [{"id": c.cid, "kind": c.kind, "region": c.region, "start_offset_hours": c.start_offset_hours,
                      "finish_offset_hours": c.finish_offset_hours, "deadline_margin_hours": c.margin_hours(w.deadline_hours),
                      "carbon_intensity": c.carbon_intensity, "energy_kwh": c.energy_kwh, "emissions_kg": c.emissions_kg}
                     for c in feas],
        "excluded": scheduler.excluded(w, all_c),
    }


@tool
def estimate_impact(workload_id: str, candidate_id: str) -> dict:
    """Estimate emissions avoided for a workload if it runs as a given candidate id, versus running now."""
    w = scheduler.get_workload(workload_id)
    if not w:
        return {"error": f"no workload {workload_id}"}
    feas = scheduler.feasible(w)
    chosen = next((c for c in feas if c.cid.upper() == candidate_id.strip().upper()), None)
    if not chosen:
        return {"error": f"candidate {candidate_id} is not a feasible option for {w.id}",
                "feasible_ids": [c.cid for c in feas]}
    return scheduler.impact(scheduler.baseline(w), chosen, w.deadline_hours)


TOOLS = [list_workloads, profile_workload, generate_candidates, estimate_impact]
