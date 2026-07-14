# ADR 0009 — S3 + Mountpoint CSI for model weights (not EBS)

**Status:** Accepted

## Decision

Store LLM model weights (Qwen3-14B AWQ safetensors) in **S3** and mount them into the vLLM
pod read-only via the **Mountpoint for S3 CSI driver** (a `ReadOnlyMany` PV), instead of
copying weights onto EBS (`gp3`) volumes.

## Rationale

- **~95% cheaper than EBS for read-once workloads.** Weights load once at pod start and are
  then served from page cache; EBS would bill for the full ~28GB volume per replica, always.
  S3 charges per GET + storage — negligible for a few-GB model loaded a handful of times/day.
- **ReadOnlyMany = every replica shares one bucket.** No per-replica volume, no snapshot
  dance. Karpenter can scale vLLM replicas up/down freely; each new pod lazy-loads from S3.
- **No EBS snapshot consistency risk.** Model versions live as immutable S3 object keys
  (`s3://<bucket>/models/qwen3-14b-awq@vN`); promoting a new version is a Helm values edit
  (`vllm.model.s3Path`), and the MLflow registry stage in CI bumps that version after evals
  pass. Rollback = point at the previous key.
- **Single source of truth.** The same S3 bucket backs Terraform (s3-bucket module), vLLM
  (Mountpoint), and MLflow (artifact store). Weights are never copied between stores.

## Consequences

- **Lazy-load = slow first start.** Mountpoint streams safetensors on demand; the first pod on
  a fresh node/PV takes 5–10 min to become ready while blocks stream from S3. We pre-warm with
  a one-shot Job that `cat`s the index files, and set a generous `readinessProbe`
  `failureThreshold` (40 × 15s = 10 min) so Karpenter doesn't mark the node unhealthy mid-load.
- **Read-only.** Mountpoint is read-only (for our use). Fine for serving; we never write model
  weights from the pod — quantization/upload happens in the CI/ML pipeline, not in-cluster.
- **IRSA, not bucket policy.** The vLLM pod's ServiceAccount carries an IRSA role granting
  `s3:GetObject` + `s3:ListBucket` on the models bucket. No node-wide IAM, no static keys.
  Terraform creates the role; the StorageClass (`s3-mountpoint`) just names the bucket.
- **Not a POSIX-perfect FS.** Mountpoint optimizes for throughput, not small/random reads; it's
  not a drop-in for general workloads. Weights loading (sequential large reads) is exactly its
  sweet spot — but don't reuse this PV for e.g. Qdrant storage or MLflow artifacts (those use
  gp3/S3 via their own operators).

## Revisit trigger

Re-evaluate if (a) model sizes grow past ~100GB and first-start latency becomes intolerable
(pre-warm insufficient → consider EBS for the hot model, S3 for the long tail), or (b) we move
off AWS (Mountpoint is AWS-specific; the generic chart uses ReadWriteOnce + MinIO/GCS, see
[[0006]]-era `values-generic.yaml`).

See `helm/mlops-platform/templates/s3-storageclass.yaml` (StorageClass) +
`templates/vllm-deployment.yaml` (the PVC + pod).