"""CarbonShift AI: an LLM does the talking (Amazon Bedrock by default), Strands Decider 2B makes
the carbon-aware scheduling decision.

CarbonShift AI helps an operator decide WHEN and WHERE a flexible cloud workload should run so
that estimated carbon emissions drop while deadlines and operational commitments are still met.
A deterministic engine (agent/scheduler.py) enforces every hard constraint and computes every
number; Strands Decider 2B (agent/decision.py) makes the bounded trade-off choice among the
feasible candidates; Amazon Bedrock runs the conversation and explains the chosen schedule.

The HackathonAgent.chat() interface is the kit contract (the demo UI, benchmark, video and AWS
deployment depend on it):

    from agent.agent import HackathonAgent
    out = HackathonAgent().chat("Schedule W-ANALYTICS-01 for the lowest carbon.")
    out["reply"], out["decisions"]
"""

from __future__ import annotations

import re
import time
from typing import Any

from strands import Agent

from decider_kit import Decider
from decider_kit.llm import agent_model, ask, default_model_id, image_blocks, strip_thinking

from . import scheduler
from .decision import CarbonShiftDecision
from .tools import TOOLS

NAME = "CarbonShift AI"

SYSTEM_PROMPT = """You are CarbonShift AI, a carbon-aware scheduling assistant for cloud workloads.
You help an operator decide when and where flexible workloads should run to cut estimated carbon
emissions while meeting deadlines and operational commitments.

You have tools to list workloads, profile a workload, generate feasible schedule candidates, and
estimate impact. Use them to answer questions about the workload queue. Be brief and precise.
You never delay an urgent or inflexible workload to improve its carbon score, and you never invent
emissions numbers or regions: every number comes from the tools. All data is synthetic and
clearly labelled as such."""

# Demos only: an eager prompt makes the agent commit to a schedule without first asking the
# operator, so the carbon-aware decision is visible on camera. Say so in the video if you use it.
EAGER_PROMPT = SYSTEM_PROMPT + """
For this demo, when the operator names a workload, go ahead and schedule it right away rather than
asking clarifying questions first."""

# Matches an explicit workload id like W-ANALYTICS-01 anywhere in the message.
_WID = re.compile(r"\bW-[A-Z0-9]+-\d+\b", re.I)
_SCHEDULE_WORDS = re.compile(r"\b(schedule|run|shift|when|where|carbon|green|clean|dispatch|place)\b", re.I)


class HackathonAgent:
    """One Strands agent per session, with the carbon-aware scheduling decision wired in."""

    def __init__(self, decider: Decider | None = None, model_id: str | None = None, eager: bool | None = None):
        import os

        self.decider = decider or Decider()
        self.eager = eager if eager is not None else os.environ.get("DEMO_EAGER") == "1"
        self.model_id = model_id or default_model_id()  # LLM_PROVIDER in .env: bedrock, local, ugmdu
        self.sessions: dict[str, tuple[Agent, CarbonShiftDecision]] = {}

    def _session(self, session_id: str) -> tuple[Agent, CarbonShiftDecision]:
        if session_id not in self.sessions:
            decision = CarbonShiftDecision(self.decider)
            agent = Agent(model=agent_model(self.model_id),
                          system_prompt=EAGER_PROMPT if self.eager else SYSTEM_PROMPT,
                          tools=TOOLS, callback_handler=None)
            self.sessions[session_id] = (agent, decision)
        return self.sessions[session_id]

    def _find_workload(self, message: str) -> scheduler.Workload | None:
        m = _WID.search(message)
        if m:
            return scheduler.get_workload(m.group(0))
        # fall back to a name mention
        for w in scheduler.load_workloads():
            if w.name.lower() in message.lower():
                return w
        return None

    def _carbon_decision(self, message: str, decision: CarbonShiftDecision) -> dict[str, Any] | None:
        """Run the carbon-aware scheduling decision when the operator asks to schedule a workload."""
        if not _SCHEDULE_WORDS.search(message):
            return None
        w = self._find_workload(message)
        if not w:
            return None
        feasible = scheduler.feasible(w)
        sel = decision.select(w, feasible)
        base = scheduler.baseline(w)
        impact = scheduler.impact(base, sel.candidate, w.deadline_hours)
        return {"workload": w, "feasible": feasible, "selection": sel, "impact": impact, "baseline": base}

    def _explain(self, message: str, trace: dict[str, Any]) -> str:
        """Ask the LLM (Amazon Bedrock) to explain the validated schedule in plain language."""
        w, sel, impact = trace["workload"], trace["selection"], trace["impact"]
        feas = trace["feasible"]
        state = scheduler.render_state(w, feas) if feas else "(no feasible candidate)"
        pref = sel.preferred
        pref_line = (f"decider_preferred: {pref.cid} ({pref.kind}, {pref.region}, {pref.emissions_kg:g} kgCO2e) "
                     f"at confidence {sel.confidence:.2f}" if pref else f"decider_preferred: none ({sel.reason})")
        final = sel.candidate
        final_line = (f"final_selected (what the application will run): {final.cid} ({final.kind}, {final.region}, "
                      f"starts in {final.start_offset_hours:g} h, {final.emissions_kg:g} kgCO2e)")
        differ = ("The application did NOT run the decider's preferred candidate; it used the deterministic "
                  "lowest-emissions fallback instead." if sel.preferred_differs else
                  "The application ran the decider's preferred candidate.")
        facts = (
            f"Operator asked: {message}\n\n{state}\n\n"
            f"--- DECISION (Strands Decider 2B) ---\n"
            f"verdict: {sel.verdict}\n{pref_line}\n{final_line}\n{differ}\n"
            f"independently_revalidated: {sel.validated} ({sel.validation_note})\n"
            f"used_fallback: {sel.used_fallback}\nneeds_operator_review: {sel.needs_review}\nwhy: {sel.reason}\n\n"
            f"--- IMPACT vs running now (for the final selected candidate) ---\n"
            f"baseline {impact['baseline_emissions_kg']:g} kgCO2e -> selected {impact['selected_emissions_kg']:g} kgCO2e; "
            f"avoided {impact['emissions_avoided_kg']:g} kgCO2e ({impact['emissions_avoided_pct']:g}%); "
            f"finishes {impact['deadline_margin_hours']:g} h before the deadline; meets_deadline: {impact['meets_deadline']}"
        )
        system = (SYSTEM_PROMPT + "\nExplain the chosen schedule to the operator in 4-6 short sentences: what the "
                  "application will run, whether that matches the decider's preferred candidate (and if it used the "
                  "fallback, say so and why), how much estimated carbon is avoided, whether the deadline is met, and "
                  "any trade-off or uncertainty. Use only the numbers given. If a fallback or review flag is set, say "
                  "so plainly. Do not invent data.")
        reply, _ = ask(facts, system=system, model_id=self.model_id, max_tokens=400)
        return strip_thinking(reply)

    def chat(self, message: str, session_id: str = "default", images: list[Any] | None = None) -> dict[str, Any]:
        """`images` is accepted for interface compatibility; the scheduling decision is text-only."""
        agent, decision = self._session(session_id)
        before = len(decision.log)
        t0 = time.perf_counter()

        trace = self._carbon_decision(message, decision)
        if trace is not None:
            # The carbon-aware decision is made in code + Decider; Bedrock explains the validated result.
            reply = self._explain(message, trace)
        else:
            result = agent([*image_blocks(images), {"text": message}] if images else message,
                           invocation_state={"images": list(images or [])})
            reply = strip_thinking(str(result))

        return {"reply": reply, "decisions": decision.log[before:], "model_id": self.model_id,
                "latency_ms": round((time.perf_counter() - t0) * 1000), "agent": NAME, "eager": self.eager}


if __name__ == "__main__":
    import json
    import sys

    a = HackathonAgent()
    for msg in sys.argv[1:] or ["What workloads are pending?",
                                "Schedule W-ANALYTICS-01 for the lowest carbon while meeting its deadline."]:
        print(json.dumps(a.chat(msg), indent=1))
