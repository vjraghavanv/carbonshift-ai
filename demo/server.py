"""Demo UI: chat with your agent and watch each Strands Decider 2B decision as it happens.

    ./kit demo            # http://localhost:8501
    DEMO_TARGET=agentcore AGENTCORE_ARN=arn:... ./kit demo     # talk to the agent deployed on AWS

The page has the conversation on the left and a decision panel on the right (each question's
probability, the verdict, and how long the decider and the whole turn took). It is also what
`./kit video` records.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from decider_kit.config import load_dotenv

load_dotenv()
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Strands Decider hackathon demo")
_agent: Any = None


class Turn(BaseModel):
    message: str
    session_id: str = "demo"
    images: list[str] = []  # base64 (data: URLs accepted), from the attach button


def agent() -> Any:
    global _agent
    if _agent is None:
        if os.environ.get("DEMO_TARGET") == "agentcore":
            _agent = AgentCoreClient(os.environ["AGENTCORE_ARN"])
        else:
            from agent.agent import HackathonAgent

            _agent = HackathonAgent()
    return _agent


class AgentCoreClient:
    """The same `chat()` interface, served by the agent deployed on Amazon Bedrock AgentCore Runtime."""

    def __init__(self, arn: str):
        import boto3

        self.arn = arn
        self.client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self.sessions: dict[str, str] = {}

    def chat(self, message: str, session_id: str = "demo", images: list[str] | None = None) -> dict[str, Any]:
        sid = self.sessions.setdefault(session_id, f"demo-{session_id}-{uuid.uuid4().hex}")
        payload = {"prompt": message, **({"images": images} if images else {})}
        r = self.client.invoke_agent_runtime(agentRuntimeArn=self.arn, runtimeSessionId=sid,
                                             payload=json.dumps(payload).encode())
        body = r["response"].read() if hasattr(r["response"], "read") else r["response"]
        out = json.loads(body)
        out["served_by"] = "Amazon Bedrock AgentCore Runtime"
        return out


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/info")
def info() -> dict[str, Any]:
    from decider_kit.config import settings

    s = settings()
    name = "Your agent"
    try:
        from agent import agent as mod

        name = getattr(mod, "NAME", name)
    except Exception:  # noqa: BLE001
        pass
    decider = s.decider_mode
    if os.environ.get("DEMO_TARGET") == "agentcore":
        dep = Path(__file__).resolve().parent.parent / "submission" / "deployment.json"
        if dep.exists():  # what the deployed agent uses, not this laptop's setting
            decider = json.loads(dep.read_text()).get("decider_mode", decider)
    from decider_kit.llm import describe

    llm = describe()
    if os.environ.get("DEMO_TARGET") == "agentcore":  # the deployed agent always uses Amazon Bedrock
        llm = f"Amazon Bedrock ({s.bedrock_model})"
    return {"agent": name, "llm": llm, "bedrock_model": s.bedrock_model, "decider": decider,
            "target": os.environ.get("DEMO_TARGET", "local")}


@app.post("/api/chat")
def chat(t: Turn) -> JSONResponse:
    try:
        a = agent()
        if t.images:
            import inspect

            if "images" not in inspect.signature(a.chat).parameters:
                return JSONResponse({"error": "this agent does not take images: add images=None to HackathonAgent.chat"},
                                    status_code=400)
            return JSONResponse(a.chat(t.message, t.session_id, images=t.images))
        return JSONResponse(a.chat(t.message, t.session_id))
    except Exception as e:  # noqa: BLE001 - shown in the UI
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/api/reset")
def reset() -> dict[str, bool]:
    global _agent
    _agent = None
    return {"ok": True}


@app.get("/api/bench")
def bench() -> JSONResponse:
    """The real benchmark result (submission/bench/results.json), summarised for the Benchmark view.

    Returns the decider-vs-LLM summary, the operating confidence threshold, and one row per
    held-out case (expected label, the decider's pick, its confidence, correct?). Graceful (empty)
    when no benchmark has been run yet. Read-only; it never invents numbers.
    """
    path = Path(__file__).resolve().parent.parent / "submission" / "bench" / "results.json"
    if not path.exists():
        return JSONResponse({"available": False})
    try:
        res = json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"available": False, "error": str(e)})
    rows = []
    for r in res.get("rows", []):
        exp = (r.get("expected") or {}).get("best_candidate")
        dec = (r.get("decider") or {}).get("best_candidate", {})
        llm = (r.get("llm") or {}).get("best_candidate", {})
        rows.append({"expected": exp, "decider": dec.get("label"), "confidence": dec.get("confidence"),
                     "llm": llm.get("label"), "correct": dec.get("label") == exp})
    # operating threshold the agent actually uses (from the pattern), falling back to the bench threshold
    op_threshold = res.get("threshold")
    try:
        from agent.decision import CONFIDENCE_THRESHOLD
        op_threshold = CONFIDENCE_THRESHOLD
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({"available": True, "summary": res.get("summary", {}), "rows": rows,
                         "split": res.get("split"), "decider_model": res.get("decider_model"),
                         "llm_model": res.get("llm_model"), "report_threshold": res.get("threshold"),
                         "operating_threshold": op_threshold})
