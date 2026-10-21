"""CarbonShift AI: the carbon-aware schedule-selection decision and its fallbacks (offline)."""

from __future__ import annotations

import pytest
from fakes import FakeDecider

from agent import scheduler
from agent.decision import CONFIDENCE_THRESHOLD, PATTERN_TAG, CarbonShiftDecision
from decider_kit.client import DeciderError


# --- the scheduling engine (deterministic, no decider) ---------------------------------------

def test_energy_and_emissions_math():
    w = scheduler.get_workload("W-ANALYTICS-01")
    assert w is not None
    assert w.energy_kwh == pytest.approx(w.avg_power_kw * w.runtime_hours)
    base = scheduler.baseline(w)
    assert base.emissions_kg == pytest.approx(base.energy_kwh * base.carbon_intensity)


def test_hard_constraints_remove_infeasible_options():
    w = scheduler.get_workload("W-ETL-02")
    feas = scheduler.feasible(w)
    # every feasible candidate finishes by the deadline
    assert all(c.finish_offset_hours <= w.deadline_hours + 1e-6 for c in feas)
    # something was excluded (the later windows that miss the deadline / margin)
    assert scheduler.excluded(w, scheduler.all_candidates(w))


def test_urgent_inflexible_only_runs_now():
    w = scheduler.get_workload("W-BILLING-03")
    feas = scheduler.feasible(w)
    assert len(feas) == 1
    assert feas[0].start_offset_hours == 0 and feas[0].is_home


def test_feasible_set_is_bounded_and_ids_stable():
    for w in scheduler.load_workloads():
        feas = scheduler.feasible(w)
        assert len(feas) <= scheduler.MAX_FEASIBLE
        assert [c.cid for c in feas] == [f"C{i}" for i in range(1, len(feas) + 1)]


def test_baseline_is_run_now_home_region():
    w = scheduler.get_workload("W-ML-04")
    base = scheduler.baseline(w)
    assert base.region == w.home_region and base.start_offset_hours == 0


# --- the decision wiring ---------------------------------------------------------------------

def _pick(cid):
    """A FakeDecider rule that always chooses candidate `cid` for the choice question."""
    return lambda state, name, q: cid


def test_decider_choice_is_used_when_confident_and_valid():
    w = scheduler.get_workload("W-ANALYTICS-01")
    feas = scheduler.feasible(w)
    target = feas[1].cid  # a real, feasible candidate that is not the fallback
    d = CarbonShiftDecision(FakeDecider(_pick(target)))
    sel = d.select(w, feas)
    assert sel.verdict == "decider"
    assert sel.candidate.cid == target
    assert not sel.used_fallback
    rec = d.log[-1]
    assert rec["pattern"] == PATTERN_TAG and rec["decider_ms"] >= 0
    # the record carries the full candidate table with emissions/time/feasibility (point 1)
    assert len(rec["candidates"]) == len(feas)
    assert all(set(c) >= {"id", "emissions_kg", "deadline_margin_hours", "feasible"} for c in rec["candidates"])
    # preferred == final here, and it is marked as not differing (points 2 & 4)
    assert rec["decider_preferred_id"] == target and rec["final_selected_id"] == target
    assert rec["preferred_differs_from_final"] is False
    # the final schedule was independently re-validated (point 5)
    assert rec["validated"] is True and rec["validation_note"]


def test_fallback_distinguishes_preferred_from_final():
    """When a fallback fires, the record shows the decider's preferred id AND the different final id."""
    w = scheduler.get_workload("W-ANALYTICS-01")
    feas = scheduler.feasible(w)
    safe = scheduler.safe_choice(feas)
    # make the decider prefer a feasible candidate that is NOT the lowest-emissions fallback,
    # but at low confidence so the fallback fires.
    preferred = next(c for c in feas if c.cid != safe.cid)

    class LowConf(FakeDecider):
        def ask(self, state, questions, images=None):
            from decider_kit.client import Decision
            return {"best_candidate": Decision(kind="choice", raw={}, label=preferred.cid,
                                               probabilities={preferred.cid: 0.4}, confidence=0.4)}
    sel = CarbonShiftDecision(LowConf()).select(w, feas)
    rec = sel  # Selection object
    assert sel.verdict == "low_confidence_fallback"
    assert sel.chosen_id == preferred.cid           # the DECIDER preferred this
    assert sel.candidate.cid == safe.cid            # the application FINALLY ran the fallback
    assert sel.preferred_differs is True
    assert sel.validated is True                    # the final fallback candidate is still re-validated


def test_only_option_skips_the_decider():
    w = scheduler.get_workload("W-BILLING-03")
    feas = scheduler.feasible(w)
    fake = FakeDecider(_pick("C1"))
    d = CarbonShiftDecision(fake)
    sel = d.select(w, feas)
    assert sel.verdict == "only_option"
    assert fake.calls == []  # the decider was never asked


def test_low_confidence_falls_back_to_lowest_emissions():
    w = scheduler.get_workload("W-ANALYTICS-01")
    feas = scheduler.feasible(w)
    # FakeDecider choice confidence is 0.85; force it below threshold with a custom Decision.
    class LowConf(FakeDecider):
        def ask(self, state, questions, images=None):
            out = super().ask(state, questions, images)
            from decider_kit.client import Decision
            a = out["best_candidate"]
            out["best_candidate"] = Decision(kind="choice", raw={}, label=a.label,
                                             probabilities={a.label: 0.4}, confidence=0.4)
            return out
    d = CarbonShiftDecision(LowConf(_pick(feas[-1].cid)), threshold=CONFIDENCE_THRESHOLD)
    sel = d.select(w, feas)
    assert sel.verdict == "low_confidence_fallback"
    assert sel.used_fallback and sel.needs_review
    assert sel.candidate == scheduler.safe_choice(feas)


def test_invalid_candidate_id_falls_back():
    w = scheduler.get_workload("W-ANALYTICS-01")
    feas = scheduler.feasible(w)
    d = CarbonShiftDecision(FakeDecider(_pick("C99")))  # not in the option set
    sel = d.select(w, feas)
    assert sel.verdict == "invalid_fallback"
    assert sel.used_fallback and sel.candidate == scheduler.safe_choice(feas)


def test_decider_unavailable_falls_back():
    class Broken(FakeDecider):
        def ask(self, state, questions, images=None):
            raise DeciderError("no server")
    w = scheduler.get_workload("W-ML-04")
    feas = scheduler.feasible(w)
    d = CarbonShiftDecision(Broken())
    sel = d.select(w, feas)
    assert sel.verdict == "error_fallback"
    assert sel.used_fallback and sel.candidate == scheduler.safe_choice(feas)


def test_infeasible_workload_is_flagged(monkeypatch):
    w = scheduler.get_workload("W-ANALYTICS-01")
    d = CarbonShiftDecision(FakeDecider())
    sel = d.select(w, [])  # no feasible candidates
    assert sel.verdict == "infeasible" and sel.needs_review


def test_impact_against_baseline():
    w = scheduler.get_workload("W-ML-04")
    feas = scheduler.feasible(w)
    chosen = scheduler.safe_choice(feas)
    imp = scheduler.impact(scheduler.baseline(w), chosen, w.deadline_hours)
    assert imp["emissions_avoided_kg"] >= 0
    assert 0 <= imp["emissions_avoided_pct"] <= 100
    assert imp["meets_deadline"] is True


# --- the agent contract ----------------------------------------------------------------------

def test_agent_chat_runs_the_carbon_decision():
    from agent.agent import HackathonAgent, NAME
    assert NAME == "CarbonShift AI"
    feas = scheduler.feasible(scheduler.get_workload("W-ANALYTICS-01"))

    class Monkeyed(HackathonAgent):
        def _explain(self, message, trace):  # avoid a real LLM call in the test
            return "ok"
    a = Monkeyed(decider=FakeDecider(_pick(feas[1].cid)), model_id="us.amazon.nova-lite-v1:0")
    out = a.chat("Schedule W-ANALYTICS-01 for the lowest carbon.")
    assert out["agent"] == "CarbonShift AI"
    assert out["decisions"] and out["decisions"][-1]["pattern"] == PATTERN_TAG
    assert "reply" in out and "latency_ms" in out and "model_id" in out
