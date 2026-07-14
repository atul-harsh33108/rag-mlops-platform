# ADR 0008 — Bifrost cascade: vLLM primary, Bedrock fallback

**Status:** Accepted

## Decision

On EKS (M5), serve Qwen3-14B AWQ from **in-cluster vLLM** on Karpenter GPU nodes as the
primary, with **AWS Bedrock (Claude 3.5 Sonnet)** as the automatic fallback. LiteLLM's proxy
`fallbacks` block routes a failed/overloaded primary to Bedrock so a Spot interruption never
surfaces as a 5xx to the client.

## Rationale

- **Cost curve.** Self-hosted vLLM on Graviton/GPU Spot is cheapest once traffic exceeds
  ~2–3M tokens/day. Below that, the GPU node sits idle and Bedrock pay-per-token is cheaper.
  Keeping vLLM as the default + Bedrock as overflow means we pay Spot prices most of the time
  and Bedrock prices only for the burst tail.
- **Spot resilience.** Karpenter consolidates/terminates vLLM nodes freely (that's the
  savings). AWS Node Termination Handler cordons + drains the node; in-flight requests on
  the dying pod fail fast. LiteLLM's `fallbacks` catches that error and retries on Bedrock —
  the client sees a latency blip, not a 5xx. This is the "Bifrost" property: traffic keeps
  flowing across the gap.
- **One gateway, one contract.** The app already calls LiteLLM (`litellmProxyUrl`); switching
  the backing model is a config edit, not a code change. The judge model for evals also rides
  Bedrock, getting its own budget (M7).
- **No vendor lock-in for the hot path.** vLLM is the primary; Bedrock is the safety net. If
  Bedrock degrades, we can add another fallback (e.g. a second vLLM replica, or another cloud
  model) without touching the app.

## Consequences

- **Latency variance.** Bedrock cold path adds ~200–600ms vs. in-cluster vLLM (~80ms). The
  fallback is acceptable precisely because it's rare; we alert if the fallback rate climbs
  (Grafana "error rate by tool" + a fallback-ratio panel).
- **Two model behaviors.** Qwen3-14B and Claude Sonnet are different models — a request that
  falls back produces a slightly different answer style. For a support assistant this is fine;
  for stricter use-cases, pin one model or add a post-fallback eval.
- **IRSA for Bedrock.** The LiteLLM pod's ServiceAccount needs `bedrock:InvokeModel`. Terraform
  creates the IRSA role; no static AWS keys. AWS_REGION is the only env the LiteLLM Bedrock
  provider needs.
- **Streaming under-count (M7).** A mid-stream Spot kill that falls back to Bedrock means the
  vLLM-side token count is partial. M7 adds a server-side final-chunk count + reconciliation
  job to close the LiteLLM-vs-Langfuse usage gap (>5% divergence alerts).

## Revisit trigger

Re-evaluate when (a) sustained traffic drops below ~1M tok/day (drop vLLM, go Bedrock-only to
kill the idle GPU), or (b) a single-region Bedrock SLA becomes insufficient (add a second
Bedrock region or a cross-cluster vLLM peer as fallback N+1).

See `docker/litellm/config.eks.yaml` for the routing + fallback block, and
`helm/mlops-platform/templates/vllm-deployment.yaml` for the vLLM pod.