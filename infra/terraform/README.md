# Terraform — AWS EKS (M5)

Provisions a production EKS cluster + the surrounding infra for the RAG platform. Two
self-contained envs compose the same modules with different sizing:

- `envs/dev/`  — staging/preview (single NAT, single-AZ RDS, destroyable)
- `envs/prod/`  — prod (multi-AZ RDS, Karpenter GPU pool, deletion-protected)

## Modules

| Module | Purpose |
|---|---|
| `vpc` | VPC + EKS/ALB subnet tagging (`terraform-aws-modules/vpc/aws`) |
| `eks` | EKS v21 (`kubernetes_version` renamed, Access Entries, built-in Karpenter) + add-ons: aws-load-balancer-controller, external-secrets, mountpoint-s3-csi, kube-prometheus-stack, loki, argo-cd |
| `ecr` | Image repos (app/pipelines/ui) + lifecycle policy |
| `rds` | Postgres metadata (app/LiteLLM/Airflow/API-keys); writes `DATABASE_URL` to Secrets Manager |
| `s3-bucket` | model weights (Mountpoint), MLflow artifacts, Langfuse blobs |
| `irsa` | IAM Role for a K8s ServiceAccount (no static keys) |
| `grafana-dashboards` | 6-panel RAG dashboard ConfigMap + PrometheusRule alerts |

## Bootstrap (once, out-of-band)

Terraform can't manage its own state bucket mid-init. Create the state bucket + lock table first:

```bash
aws s3api create-bucket --bucket mlops-tf-state-prod --region us-east-1 \
  --create-bucket-configuration LocationConstraint=us-east-1
aws s3api put-bucket-versioning --bucket mlops-tf-state-prod \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket mlops-tf-state-prod \
  --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws dynamodb create-table --table-name mlops-tf-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
# Repeat for mlops-tf-state-dev.
```

## Apply

```bash
cd infra/terraform/envs/prod
export TF_VAR_grafana_admin_password="$(openssl rand -base64 24)"
# Edit terraform.tfvars: github_repo, bucket names, region.
terraform init -backend-config=false   # backend is in providers.tf; init pulls providers
terraform plan
terraform apply
```

GitHub OIDC for CI: create the GitHub OIDC provider in AWS once (the `ci_deploy` role trusts
`token.actions.githubusercontent.com`), then add the role ARN as `AWS_DEPLOY_ROLE_ARN` to the
repo's Actions secrets (CI assumes it via `aws-actions/configure-aws-credentials`).

## Outputs you'll need

- `ci_deploy_role_arn`  → CI `AWS_DEPLOY_ROLE_ARN` secret
- `ecr_repository_urls` → CI image push targets (`values-eks.yaml` image repos)
- `app_irsa_role_arn` / `vllm_irsa_role_arn` / `langfuse_irsa_role_arn` → Helm `serviceAccount.annotations.eks.amazonaws.com/role-arn`
- `db_secret_name` → referenced by the `app-db-url` ExternalSecret (created in-cluster)
- `cluster_name` / `cluster_endpoint` → kubeconfig + Argo CD target

## Gotchas (see docs/decisions/0008-bifrost-bedrock-vllm.md + 0009-s3-mountpoint.md)

- **Mountpoint lazy-loads** — first vLLM pod on a fresh PV takes 5–10 min while safetensors
  stream from S3. Pre-warm with a one-shot Job `cat`-ing the index, or Karpenter may mark the
  node unhealthy mid-load.
- **Spot interruption → Bedrock**: AWS Node Termination Handler drains vLLM nodes; in-flight
  requests fail to Bedrock via the LiteLLM fallback chain (not a 5xx to the client).
- **State bucket is not managed here** — create out-of-band (above). Editing it via Terraform
  would lock you out of your own state.
- **`kubernetes_version`** is the v21 module's renamed `cluster_version`.
- **Access Entries** replace `aws-auth` ConfigMap (no more `aws_auth` arg).

## Verification (no terraform in dev env)

We can't `terraform validate` without the binary here. Structural checks: brace/paren balance
on every `.tf`, and the Grafana dashboard JSON parses. Run `terraform fmt -recursive && terraform validate`
in WSL where terraform is installed.