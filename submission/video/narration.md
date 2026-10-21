0. CarbonShift AI runs on Amazon Bedrock AgentCore Runtime and talks through Amazon Bedrock. Strands Decider chooses the best execution window and region among the feasible candidates for each workload.

1. CarbonShift AI decides when and where a flexible cloud workload should run to cut estimated carbon, without missing deadlines. What it does: A workload queue with deadline, priority and flexibility for each job. A deterministic engine that enforces hard constraints and estimates energy and emissions. A carbon-aware candidate choice made by Strands Decider 2B, with live confidence and latency. A safe fallback and an operator-review flag when the decision is low-confidence.

2. The agent you are about to see is running on Amazon Bedrock AgentCore Runtime.

3. The operator looks at the queue: flexible analytics, a deadline-constrained ETL, an urgent billing job and more. No decision was needed on this turn.

4. A flexible analytics job with plenty of slack: cleaner windows and regions are open, so a real trade-off choice is made. The decider scored confidence 0.68, so the verdict was decider, in 3.9 seconds.

5. A high-priority report with a tighter deadline: the greenest option must still keep a safe margin. The decider scored confidence 0.75, selected start offset hours 0.00, selected emissions kg 0.60, so the verdict was decider, in 2.2 seconds.

6. Urgent and not flexible: only an immediate run is feasible, so carbon cannot delay it. The decider scored confidence 1.00, selected start offset hours 0.00, selected emissions kg 0.42, so the verdict was only_option.

7. On 13 labelled decisions, with the decider on the AWS User Group Madurai hosted API, Strands Decider was 100% accurate at a median of 3278 milliseconds, against 100% and 4906 milliseconds for a hosted open LLM asked the same questions.

8. Hard constraints in code, a calibrated carbon-vs-deadline choice from Strands Decider in one forward pass, and Amazon Bedrock for the explanation.