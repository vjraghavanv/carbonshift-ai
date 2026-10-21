"""REUSABLE DECISION PATTERN: carbon-aware schedule selection  (#tool-selection)

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
        final  = chosen if (chosen and ans.confidence >= THRESHOLD and revalidate(chosen)) \
                 else safe_default(options)                   # fallback + flag for review

    Keep the three invariants: (a) hard constraints and all arithmetic in code, never in the
    model; (b) the decider classifies, your code acts; (c) the final choice is independently
    re-validated and the model can never override a hard constraint. `CarbonShiftDecision` below
    is this shape with carbon scheduling filled in; `select()` holds the thresholds you would tune.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from decider_kit import Decider
from decider_kit.client import DeciderError

from . import scheduler
from .scheduler import Candidate, Workload

PATTERN_TAG = "#tool-selection"

# Below this confidence the decider does not act alone: fall back to the deterministic safe choice
# (lowest-emissions feasible candidate) and flag for operator review. A module constant, tunable.
CONFIDENCE_THRESHOLD = 0.6

# The most feasible candidates we ever present in one decision. Keeping the option set small and
# bounded is what makes the choice tractable and the benchmark stable.
MAX_CANDIDATES = 5

# Fixed option set for the benchmark and the decider: the per-candidate detail is in the state,
# so each id's "meaning" just points at the candidate shown under that id.
CANDIDATE_IDS = [f"C{i}" for i in range(1, MAX_CANDIDATES + 1)]
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


@dataclass
class Selection:
    candidate: Candidate                 # the FINAL candidate the application selected (after fallback/validation)
    verdict: str  # decider | only_option | low_confidence_fallback | invalid_fallback | error_fallback | infeasible
    confidence: float = 0.0
    chosen_id: str | None = None         # the candidate id the DECIDER preferred (may differ from candidate.cid)
    preferred: Candidate | None = None   # the Candidate object the decider preferred, when it is a valid id
    probabilities: dict[str, float] = field(default_factory=dict)
    decider_ms: float = 0.0
    used_fallback: bool = False
    needs_review: bool = False
    validated: bool = False              # did the FINAL candidate pass an independent re-check? (US-5)
    validation_note: str = ""
    reason: str = ""

    @property
    def preferred_differs(self) -> bool:
        """True when the application's final schedule is NOT the decider's preferred candidate."""
        return bool(self.chosen_id and self.chosen_id != self.candidate.cid)


class CarbonShiftDecision:
    """Hands the feasible candidate set to Strands Decider 2B and turns the answer into a schedule."""

    def __init__(self, decider: Decider, threshold: float = CONFIDENCE_THRESHOLD):
        self.decider = decider
        self.threshold = threshold
        self.log: list[dict[str, Any]] = []

    def _questions_for(self, cands: list[Candidate]) -> dict[str, dict[str, Any]]:
        """Only the ids actually present, so the decider never picks an empty slot."""
        ids = [c.cid for c in cands]
        return {"best_candidate": Decider.choice(QUESTIONS["best_candidate"]["instructions"],
                                                 {cid: QUESTIONS["best_candidate"]["criteria"][cid] for cid in ids})}

    def _confirm(self, w: Workload, c: Candidate) -> tuple[bool, str]:
        """Independent re-check of the FINAL candidate against every hard constraint (US-5)."""
        ok = c in scheduler.feasible(w)
        note = (f"re-validated against hard constraints: finishes {c.margin_hours(w.deadline_hours):g} h before the "
                f"deadline, region {c.region} eligible, capacity ok") if ok else "FAILED independent re-validation"
        return ok, note

    def select(self, w: Workload, cands: list[Candidate]) -> Selection:
        if not cands:
            sel = Selection(candidate=scheduler.baseline(w), verdict="infeasible", needs_review=True,
                            validated=False, validation_note="no feasible candidate to validate",
                            reason="no feasible candidate meets the hard constraints")
            self.log.append(self._record(w, sel, cands))
            return sel

        if len(cands) == 1:
            ok, note = self._confirm(w, cands[0])
            sel = Selection(candidate=cands[0], verdict="only_option", confidence=1.0, chosen_id=cands[0].cid,
                            preferred=cands[0], validated=ok, validation_note=note,
                            reason="only one feasible candidate; no decision needed")
            self.log.append(self._record(w, sel, cands))
            return sel

        safe = scheduler.safe_choice(cands)
        by_id = {c.cid: c for c in cands}
        state = scheduler.render_state(w, cands)

        try:
            answers = self.decider.ask(state, self._questions_for(cands))
            a = answers["best_candidate"]
            chosen_id, confidence = a.label, a.confidence
            probs = a.probabilities
            decider_ms = self.decider.last_latency_ms or 0.0
        except DeciderError as e:
            ok, note = self._confirm(w, safe)
            sel = Selection(candidate=safe, verdict="error_fallback", chosen_id=None, preferred=None, used_fallback=True,
                            needs_review=True, validated=ok, validation_note=note,
                            reason=f"decider unavailable ({type(e).__name__}); used lowest-emissions fallback")
            self.log.append(self._record(w, sel, cands))
            return sel

        preferred = by_id.get(chosen_id)
        common = {"confidence": round(confidence, 4), "chosen_id": chosen_id, "preferred": preferred,
                  "probabilities": {k: round(v, 4) for k, v in probs.items()}, "decider_ms": round(decider_ms)}

        if chosen_id not in by_id:
            final, verdict, fb, review = safe, "invalid_fallback", True, True
            reason = f"decider preferred {chosen_id!r}, which is not in the option set; used lowest-emissions fallback"
        elif confidence < self.threshold:
            final, verdict, fb, review = safe, "low_confidence_fallback", True, True
            reason = (f"decider preferred {chosen_id} but confidence {confidence:.2f} is below {self.threshold:.2f}; "
                      f"used lowest-emissions fallback and flagged for operator review")
        elif not self._confirm(w, preferred)[0]:
            final, verdict, fb, review = safe, "invalid_fallback", True, True
            reason = f"decider preferred {chosen_id} but it failed independent re-validation; used lowest-emissions fallback"
        else:
            final, verdict, fb, review = preferred, "decider", False, False
            reason = f"Strands Decider 2B preferred {chosen_id} (confidence {confidence:.2f}); accepted after re-validation"

        ok, note = self._confirm(w, final)  # the FINAL candidate is always independently re-validated
        sel = Selection(candidate=final, verdict=verdict, used_fallback=fb, needs_review=review,
                        validated=ok, validation_note=note, reason=reason, **common)
        self.log.append(self._record(w, sel, cands))
        return sel

    @staticmethod
    def _cand_row(w: Workload, c: Candidate, feasible_ids: set[str]) -> dict[str, Any]:
        return {"id": c.cid, "kind": c.kind, "region": c.region, "start_offset_hours": c.start_offset_hours,
                "finish_offset_hours": c.finish_offset_hours, "deadline_margin_hours": c.margin_hours(w.deadline_hours),
                "carbon_intensity": c.carbon_intensity, "emissions_kg": c.emissions_kg,
                "feasible": c.cid in feasible_ids}

    def _record(self, w: Workload, sel: Selection, cands: list[Candidate]) -> dict[str, Any]:
        feasible_ids = {c.cid for c in cands}
        preferred_id = sel.chosen_id
        final_id = sel.candidate.cid
        return {
            "pattern": PATTERN_TAG,
            "workload": w.id,
            "verdict": sel.verdict,
            # the full option set the decider chose among, with every number and feasibility (points 1)
            "candidates": [self._cand_row(w, c, feasible_ids) for c in cands],
            # what the DECIDER preferred vs what the application FINALLY selected (points 2 and 4)
            "decider_preferred_id": preferred_id,
            "final_selected_id": final_id,
            "preferred_differs_from_final": sel.preferred_differs,
            "confidence": round(sel.confidence, 4),
            "probabilities": sel.probabilities,
            "decider_ms": round(sel.decider_ms),
            # independent validation of the FINAL schedule (point 5, US-5)
            "validated": sel.validated,
            "validation_note": sel.validation_note,
            # why (point 3)
            "used_fallback": sel.used_fallback,
            "needs_review": sel.needs_review,
            "reason": sel.reason,
            # kept for back-compat with the benchmark and the earlier record shape
            "chosen_id": preferred_id,
            "selected_id": final_id,
            "selected_region": sel.candidate.region,
            "selected_start_offset_hours": sel.candidate.start_offset_hours,
            "selected_emissions_kg": sel.candidate.emissions_kg,
        }
