# mlops-platform Helm chart

Production-grade RAG MLOps platform, deployed as one umbrella chart across three
environments. See `infra/k8s-bootstrap/README.md` for the GitOps workflow.

## Values files

| File | Env | Notes |
|---|---|---|
| `values.yaml` | base | shared defaults |
| `values-kind.yaml` | local k3d/kind (M4) | side-loaded images, local-path storage, CPU Ollama/TEI |
| `values-eks.yaml` | AWS EKS (M5) | 3-node Qdrant Raft, ALB ingress, Bedrock/vLLM via LiteLLM, HPA |
| `values-generic.yaml` | any K8s (M6) | ingress-nginx + cert-manager + Let's Encrypt |

## Install (local K8s)

```bash
task k3d:up        # cluster + registry
task k3d:load      # build + side-load mlops/app:0.1.0
task helm:install  # helm upgrade --install -f values-kind.yaml -n mlops
kubectl port-forward svc/mlops-app 8000:8000 -n mlops
curl localhost:8000/health
```

## Dependencies

Active (HTTP repos, `helm dep build` pulls them): **qdrant** `0.7.6`, **ingress-nginx**
`4.11.2`. The full stack (mlflow, langfuse, litellm, airflow, argo-cd, cert-manager,
external-secrets) is in `Chart.yaml` as **commented** entries — uncomment + `helm dep build`
to enable (progressive enablement, keeps the local demo lightweight).

### Bitnami gotcha (Aug 2025)
Bitnami moved free charts to OCI (`oci://registry-1.docker.io/bitnamicharts`) and legacy
images to `bitnamilegacy/*`. For Bitnami charts, pin `image.repository=bitnamilegacy/...`
in the values file.

## Argo CD

Argo renders the chart **template-only** — `helm list` won't show the release. Helm init
hooks (e.g. `ollama-init`) aren't deleted on render, so every hook in this chart is
idempotent and uses `before-hook-creation,hook-succeeded` delete policy. See
`infra/k8s-bootstrap/argocd-apps.yaml`.

## App subchart (`charts/app/`)

The FastAPI RAG service. Renders Deployment + Service + ConfigMap + (optional) Secret +
Ingress + HPA. Non-secret config in the ConfigMap; the DB URL + API keys in the Secret
(M5/M6 replace the Secret with External Secrets Operator + IRSA — never inline prod creds).

## RLS note

Qdrant tenant isolation is enforced server-side in the app (`filter_builder.py`), not in
the chart — the chart just provides the infra. Cross-tenant isolation is asserted in
`app/tests/test_filter_builder.py` + `test_retriever_rls.py` (CI security gate).