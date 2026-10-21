# Use case — CarbonShift AI

**Schedule Smarter. Compute Cleaner.** — by Koodal AI Labs

- **Pitch:** CarbonShift AI helps a cloud operator decide *when* and *where* a flexible workload
  should run so that estimated carbon emissions drop while deadlines and operational commitments
  are still met.
- **Who it is for:** platform and SRE teams who run flexible batch, analytics, ETL, reporting and
  ML-training jobs and want to cut the carbon of that compute without missing deadlines.
- **Features:**
  - a workload queue with runtime, power, deadline, priority and flexibility for each job;
  - a deterministic scheduling engine that generates feasible execution windows across eligible
    regions and enforces every hard constraint (deadline, capacity, eligibility, flexibility) in
    code before anything is decided;
  - per-candidate estimated energy (kWh) and emissions (kg CO2e) from a documented model;
  - a carbon-aware candidate choice made by Strands Decider 2B, with a live decision panel in the
    demo UI showing the feasible options, the excluded ones, the chosen candidate, its confidence
    and its latency;
  - low-confidence, invalid-choice and service-failure handling: a deterministic safe fallback
    (lowest-emissions feasible candidate) plus an operator-review flag;
  - an impact comparison against running now (baseline), with absolute and percentage carbon
    avoided and the deadline margin;
  - deployed on Amazon Bedrock AgentCore Runtime.
- **The decision handed to Strands Decider 2B:** among the feasible schedule candidates (hard
  constraints already enforced), which one best balances lower estimated carbon against a safe
  deadline margin and the workload's priority? A `choice` over candidate ids. (`#tool-selection`)
- **Why a decision model:** this is a judgement, not arithmetic. The literal lowest-emissions
  option is a one-line `min()` in code; the real call is the trade-off between carbon saved and
  deadline risk for a given priority, which reasonable operators weigh differently. The decider
  returns a calibrated confidence the code branches on, fast and cheap, on every schedule.
- **Amazon Bedrock:** the operator conversation and the plain-language explanation of the chosen
  schedule, trade-offs and impact (Amazon Nova Pro by default).

**Honesty note:** all workload and carbon-intensity data in `agent/data/` is synthetic and
labelled as such. Estimated emissions cover the workload's operational electricity only (energy x
grid carbon intensity); they are not AWS's whole footprint and not embodied or PUE-adjusted carbon.
The data-provider seam in `agent/data/` lets a real carbon-intensity source be added later.
