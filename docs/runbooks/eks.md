# Runbook — AWS EKS production (M5)

Terraform provisions the cluster + surrounding infra; the Helm umbrella chart (deployed via
Argo CD) runs the app layer on top of it. This runbook is the happy path from zero to a
serving, observed, resilient RAG stack on EKS. Assumes WSL2 + Docker Desktop per
`docs/runbooks/local.md`, plus `aws-cli`, `terraform 1.9+`, `kubectl`, `helm`, `gh` installed.

## Prerequisites (one-time, AWS console / CLI)

1. **GitHub OIDC provider** in AWS — lets CI assume a role without static keys. Create once:
   ```bash
   # Add the GitHub OIDC IdP to IAM (thumbprint via docs/decisions or the aws-actions README).
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com \
     --thumbprint-list 6938fd4d2bab87fa37bf6c4ebf6c4edf67c2e8a5
   ```
   Terraform creates the `ci_deploy` role trusting `token.actions.githubusercontent.com` +
   your repo; copy its ARN (`terraform output ci_deploy_role_arn`) into the repo Actions
   secret `AWS_DEPLOY_ROLE_ARN`.

2. **State bucket + lock table** — Terraform can't manage its own state bucket mid-init.
   Bootstrap out-of-band per `infra/terraform/README.md` (one `mlops-tf-state-{dev,prod}`
   bucket + a `mlops-tf-lock` DynamoDB table each).

3. **Bedrock model access** — in the Bedrock console, enable `anthropic.claude-3-5-sonnet`
   in your region. The Bifrost fallback silently fails until this is granted.

## 1. Apply Terraform (dev first, then prod)

```bash
cd infra/terraform/envs/dev
export TF_VAR_grafana_admin_password="$(openssl rand -base64 24)"
# Edit terraform.tfvars: github_repo, bucket names, region.
terraform init
terraform plan
terraform apply
```

Outputs you'll need for Helm (note them now):

| Output | Used in |
|---|---|
| `cluster_name` / `cluster_endpoint` | kubeconfig, Argo CD target |
| `ecr_repository_urls` | `values-eks.yaml` `image.repository` |
| `app_irsa_role_arn` | app SA annotation (wired by chart) |
| `vllm_irsa_role_arn` | `values-eks.yaml` `vllm.irsaRoleArn` |
| `langfuse_irsa_role_arn` | Langfuse SA annotation |
| `db_secret_name` | `app-db-url` ExternalSecret (created in-cluster) |
| `ci_deploy_role_arn` | repo Actions secret `AWS_DEPLOY_ROLE_ARN` |

```bash
aws eks update-kubeconfig --name mlops-dev --region us-east-1
# Repeat for envs/prod with TF_VAR_grafana_admin_password set to a NEW value, deletion_protection=true.
```

## 2. Fill in `values-eks.yaml`

Terraform outputs fill the blanks in `helm/mlops-platform/values-eks.yaml`:

- `app.image.repository` / `ui.image.repository` → ECR repo URLs (or keep GHCR; CI pushes to both)
- `vllm.irsaRoleArn` → `vllm_irsa_role_arn` output
- `vllm.model.bucket` / `s3Path` → models bucket + key
- Clerk keys (`clerkPublishableKey`/`clerkSecretKey`) → leave empty; ExternalSecret injects them

Also **uncomment the full-stack dependencies** in `helm/mlops-platform/Chart.yaml` (langfuse,
litellm, airflow, mlflow, argo-cd, cert-manager, external-secrets) — they're commented so the
local M4 demo builds without pulling heavy charts. Then `helm dep build helm/mlops-platform`.

## 3. GitOps: Argo CD

Terraform installs Argo CD and bootstraps an `ApplicationSet` pointing at this repo. Push
`values-eks.yaml` + the uncommented `Chart.yaml` to `main`; Argo reconciles:

```bash
kubectl get pods -n argocd
argocd admin initial-password   # or read from the secret per the Terraform output
# Argo UI: port-forward argocd-server, sign in, watch mlops-dev sync.
argocd app wait mlops-dev --sync --health --timeout 600s
```

Argo renders the umbrella chart (init hooks are idempotent — `GenerateName` +
`hook-delete-policy: before-hook-creation,hook-succeeded`).

## 4. External Secrets

The `app-db-url` ExternalSecret (created by Terraform via the kubectl provider) pulls the
`DATABASE_URL` from AWS Secrets Manager into a K8s Secret the app mounts via
`existingDbUrlSecret: app-db-url`. Verify:

```bash
kubectl get externalsecret app-db-url -n mlops
kubectl get secret app-db-url -n mlops -o jsonpath='{.data.DATABASE_URL}' | base64 -d   # spot-check, don't log
```

## 5. vLLM + Mountpoint pre-warm

First vLLM pod lazy-loads safetensors from S3 (5–10 min). Pre-warm so Karpenter doesn't mark
the node unhealthy mid-load:

```bash
kubectl apply -f - <<'EOF'
apiVersion: batch/v1
kind: Job
metadata: { name: warm-models, namespace: mlops }
spec:
  template:
    spec:
      restartPolicy: OnFailure
      nodeSelector: { pool: gpu }
      tolerations: [{ key: nvidia.com/gpu, operator: Exists }]
      containers:
        - name: warm
          image: public.ecr.aws/amazonlinux/aws-cli:2
          command: ["/bin/sh","-c"]
          args: ["aws s3 cp s3://$(BUCKET)/models/qwen3-14b-awq/config.json - >/dev/null && echo warmed"]
          env: [{ name: BUCKET, value: mlops-prod-models }]
EOF
```

(Or `kubectl exec` into the vLLM pod and `cat /models/.../safetensors.index.json`.) Watch:

```bash
kubectl rollout status deploy/mlops-vllm -n mlops
kubectl logs -n mlops -l app.kubernetes.io/name=vllm --tail=50
```

## 6. Smoke test + resilience drill

```bash
# Smoke
curl -fsS https://rag.example.com/chat \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer sk-acme-...' \
  -d '{"question":"How do I reset my password?","stream":false}' | jq .
```

Resilience (Bifrost): cordon the vLLM node mid-stream and confirm no 5xx — Bedrock takes over:

```bash
NODE=$(kubectl get pod -n mlops -l app.kubernetes.io/name=vllm -o jsonpath='{.items[0].spec.nodeName}')
kubectl cordon $NODE
# Start a long streaming request in another shell, then drain:
kubectl drain $NODE --ignore-daemonsets --delete-emptydir-data --force --grace-period=30
# The in-flight stream should complete via Bedrock (Langfuse trace shows the fallback model), not 5xx.
kubectl uncordon $NODE
```

## 7. Observability — Grafana 6-panel + alerts

```bash
kubectl port-forward -n monitoring svc/mlops-grafana 3000:80
# admin / TF_VAR_grafana_admin_password
```

Dashboard: **RAG overview** (6 panels: request/error rate · p50/p95 latency · latency heatmap
by model · cost per turn · top-10 slowest traces · error rate by tool). Langfuse is wired as a
Postgres datasource via a read-only `grafana_reader` role.

Alerts (`PrometheusRule`):
- `RagP95LatencyHigh` — p95 > 8s for 5m
- `RagErrorRateHigh` — error rate > 5%
- `RagNoInfoHigh` — "no info" answer rate > 25% for 15m
- `RagSpendHigh` — LLM spend > $2/h

## CI (OIDC → ECR + Gitleaks)

`.github/workflows/ci.yml` on `push: main`:
- Builds app/pipelines/ui, Trivy scans (fail HIGH/CRITICAL), cosign signs, syft SBOM
- Pushes to **GHCR** always; pushes to **ECR** via OIDC (`aws-actions/configure-aws-credentials`
  assuming `ci_deploy_role_arn` — no static AWS keys)
- **Gitleaks** scans the repo for committed secrets (fails the build on a hit)

`.github/workflows/deploy.yml` on `push: main`:
- Bumps the **digest-pinned** image tag in `values-eks.yaml` via `yq`
  (`ghcr.io/.../app@sha256:...`), commits, Argo auto-syncs `mlops-dev`
- Smoke test → manual approval (GitHub `production` environment) → `argocd app sync mlops-prod`
- Rollback = `git revert` the bump commit.

## Gotchas (full list in ADRs 0008 + 0009 + terraform README)

- **Mountpoint lazy-loads** — pre-warm or first-start is 5–10 min (ADR 0009).
- **Spot interruption → Bedrock** — drain in-flight, don't just fail new requests (ADR 0008).
- **State bucket is out-of-band** — never manage it via Terraform.
- **`kubernetes_version`** is the EKS module v21 rename of `cluster_version`.
- **Access Entries** replace `aws-auth` (no more `aws_auth` arg).
- **Bedrock region enablement** — the fallback is silent-fail until the model is enabled in-region.
- **Langfuse Postgres + grafana_reader** — the read-only SQL user + datasource are wired by
  Terraform; if you self-host Langfuse without that module, add the user manually.