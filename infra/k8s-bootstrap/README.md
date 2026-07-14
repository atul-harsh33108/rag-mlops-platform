# Kubernetes bootstrap (M4)

GitOps layout: this repo is the single source of truth. Argo CD watches it and renders
the umbrella chart per environment.

```
helm/mlops-platform/        the chart (source of truth)
  ├── Chart.yaml            active deps: qdrant, ingress-nginx; full stack commented
  ├── values.yaml           base
  ├── values-kind.yaml      local k3d/kind (M4)
  ├── values-eks.yaml       AWS EKS (M5)
  ├── values-generic.yaml  any K8s (M6)
  ├── charts/app/           the FastAPI RAG service (local subchart)
  └── templates/            namespace + optional Ollama/TEI StatefulSets
infra/k8s-bootstrap/
  └── argocd-apps.yaml      AppProject + mlops-dev / mlops-prod Applications
```

## Local K8s (k3d) — the M4 demo

```bash
task k3d:up          # cluster + in-cluster registry (mlops-registry:5000)
task k3d:load       # build docker/Dockerfile.app -> tag mlops/app:0.1.0 -> push to k3d registry
task helm:install   # helm upgrade --install mlops ./helm/mlops-platform -f values-kind.yaml -n mlops
kubectl rollout status deploy/mlops-app -n mlops
kubectl port-forward svc/mlops-app 8000:8000
curl localhost:8000/health
```

## Argo CD GitOps

```bash
# one-time: install Argo CD into the cluster (M4 — or enable the argo-cd dep in Chart.yaml)
# kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml -n argocd

# wire the apps (replace <GIT_REPO_URL> in argocd-apps.yaml first):
sed -i 's#<GIT_REPO_URL>#https://github.com/<org>/mlops#' infra/k8s-bootstrap/argocd-apps.yaml
kubectl apply -f infra/k8s-bootstrap/argocd-apps.yaml
task argocd:wait     # argocd app wait mlops-dev --sync --health
```

`mlops-dev` auto-syncs from `main`; `mlops-prod` is manual (an operator clicks Sync, or
CI's `deploy.yml` runs `argocd app sync mlops-prod` after approval).

## Enabling the full stack

The umbrella ships with only `qdrant` + `ingress-nginx` as active Helm dependencies so
`helm dep build` works out of the box. To add MLflow/Langfuse/LiteLLM/Airflow/Argo CD:
uncomment the matching block in `helm/mlops-platform/Chart.yaml`, set `<chart>.enabled: true`
in the env values file, and `helm dep build` again.

**Bitnami gotcha (Aug 2025):** Bitnami moved free charts to OCI at
`oci://registry-1.docker.io/bitnamicharts` and legacy images to `bitnamilegacy/*`. For
Bitnami charts, pin `image.repository=bitnamilegacy/...` in the values file.

## CI (`.github/workflows/ci.yml`)

PRs run: uv lock/ruff/pytest → build app image → Trivy (SARIF, fail HIGH/CRITICAL) →
cosign sign (keyless) + syft SBOM → push to GHCR on `main`. **No deploy from PRs.**
`deploy.yml` (main) bumps the digest-pinned tag in `values-eks.yaml` via `yq` → Argo
syncs → smoke test → manual approval → promote.