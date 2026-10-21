# Notebooks

## carbonshift_ai.ipynb

A runnable, cell-by-cell tour of the CarbonShift AI decision: the deterministic scheduler and its
hard constraints, the feasible candidate set, the Strands Decider 2B `choice` (offline with a
`FakeDecider`, plus an optional live call), the low-confidence fallback and the preferred-vs-final
distinction, and the real benchmark result loaded from `submission/bench/results.json`.

Run it from the repo root so `agent/` and `decider_kit/` import. The offline cells need no key; the
one optional "real decider" cell uses your `.env` if a reachable decider is configured and is safe
to skip otherwise.

```bash
# regenerate from the kit code (the notebook is produced by a script, so it never drifts):
.venv/bin/python scripts/gen_notebook.py

# open it:
jupyter notebook notebooks/carbonshift_ai.ipynb   # or VS Code / SageMaker Studio
```

On Amazon SageMaker Studio: upload the repo (or clone it), open the notebook, pick a Python 3
kernel, and run all cells. The live decider cell reads `DECIDER_URL` / `DECIDER_API_KEY` from
`.env`; set them in the notebook environment if you want the real call.

Built with the AWS User Group Madurai Strands Decider hackathon kit.
