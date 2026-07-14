# Runbook — Local dev (Windows 11 + WSL2)

## One-time setup

### 1. WSL2 + Docker Desktop
- Install **WSL2 Ubuntu 24.04**: `wsl --install -d Ubuntu-24.04` (Windows admin shell); `wsl --set-default Ubuntu-24.04`.
- Install **Docker Desktop 4.40+**; Settings → Resources → WSL Integration → enable for your distro.
- **Put the repo on ext4 inside WSL**, e.g. `~/mlops` (clone or symlink). **Do not work from `/mnt/c/Project/MLOPs`** — the 9P filesystem is 3–5x slower and breaks file-watch hot reload.

### 2. `.wslconfig` (at `%USERPROFILE%\.wslconfig`)
Copy `.wslconfig.example` and tune. Bump `memory` (vLLM + Postgres + Qdrant + Airflow together need it; default WSL gives only half host RAM and may OOM-kill vLLM). `sparseVhd=true` limits disk bloat. Set `networkingMode=mirrored` **only if behind a VPN**.

### 3. NVIDIA GPU (optional but recommended for local 14B)
- Install the **NVIDIA Windows driver 560+** — that's it on Windows.
- **Never** install `cuda` or `cuda-drivers` meta-packages inside WSL2; the Windows driver auto-stubs `libcuda.so`. Install only `cuda-toolkit-12-6`/`13-2` if you need `nvcc`.
- Verify inside WSL: `nvidia-smi` lists your GPU.
- Verify Docker GPU: `docker run --rm -it --gpus=all nvcr.io/nvidia/k8s/cuda-sample:nbody nbody -gpu -benchmark`.
- Performance is ~95–100% of native Linux.

### 4. Tooling inside WSL
```bash
sudo apt update && sudo apt install -y git curl build-essential
# uv (Python)
curl -LsSf https://astral.sh/uv/install.sh | sh
# kubectl, helm, k3d, kind, terraform, aws-cli, gh, task
# (use the official installers / apt repos / brew-on-linux as you prefer)
# Node 22 LTS (for the UI at M6): use nvm or the NodeSource repo
```
Keep `helm` and `kubectl` versions aligned across Windows PowerShell and WSL.

### 5. Git line endings
The repo's `.gitattributes` forces `eol=lf`. Also set once globally: `git config --global core.autocrlf input`. This prevents Helm charts / shell scripts from breaking under CRLF.

## Daily loop

```bash
cd ~/mlops
cp .env.example .env        # fill CHANGE_ME values (randomize secrets: openssl rand -hex 32)

# M1+M2 — RAG + observability:
task dev:up core,ai,mlops    # Qdrant, TEI, Ollama, Redis, app, Open WebUI, Langfuse, MLflow, OTel
task seed
curl -N http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"How do I reset my password?","tenant":"acme"}'
# UI:   http://127.0.0.1:3000   Open WebUI
# Docs: http://127.0.0.1:8000/docs

# M6 — customer-facing Next.js UI (Clerk auth, AI SDK useChat, citations):
task ui:install                 # npm install (once)
task dev:up core,ai,ui         # adds the Next.js UI on :3002
# UI:   http://127.0.0.1:3002
# Without CLERK_* env, the UI queries the `acme` tenant (LOCAL_DEV_TENANT) via the backend
# no-auth path. To enable Clerk: set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY + CLERK_SECRET_KEY
# in .env, then sign in and switch Organization (= tenant) from the header.

# M3 — gateway + orchestration (add gateway + orch profiles):
task dev:up core,ai,gateway,mlops,orch
task prompt:register         # register rag_system.md -> MLflow Prompt Registry @production
task ingest:full             # trigger the Airflow ingest_full DAG (corpus -> Qdrant)
# Watch the Asset chain in the Airflow UI: ingest_full -> reindex_on_change -> evals_canary
# LiteLLM UI:   http://127.0.0.1:4000   (per-key spend)
# Airflow UI:   http://127.0.0.1:8080   (admin / $AIRFLOW_ADMIN_PASSWORD)
task spend:view               # apply tenant_spend_monthly view (once, after LiteLLM boots)
task spend:monthly            # per-tenant monthly LLM spend
task dev:down
```

> With the `gateway` profile up, the app routes all LLM traffic through LiteLLM
> (`LITELLM_PROXY_URL`), which logs per-call spend to the `litellm` Postgres DB — the
> foundation for M7 billing. Without the profile, the app talks to Ollama directly.

## Ports (localhost, bound to 127.0.0.1 only)

| Port | Service |
|---|---|
| 3000 | Open WebUI (demo chat) |
| 3001 | Langfuse web (M2) |
| 3002 | Next.js customer UI (M6) |
| 4000 | LiteLLM proxy UI (M3) |
| 5000 | MLflow (M2) |
| 6333 | Qdrant |
| 8000 | FastAPI app |
| 8080 | Airflow UI (M3) |
| 9090 | Prometheus (M5) |
| 3100 | Loki (M5) |

## Gotchas

- **OOM kills vLLM**: bump `.wslconfig` memory; for local M1 use Ollama (lighter) instead of vLLM.
- **VPN**: set `networkingMode=mirrored` or `wsl --shutdown` after network changes; otherwise kind/k3d port forwarding misbehaves.
- **Disk bloat**: `wsl --manage Ubuntu-24.04 --set-sparse true` + compact the VHDX periodically (`Optimize-VHD`).
- **`/mnt/c` slowness**: keep repos on `~/` ext4; edit from Windows via the `\\wsl$\Ubuntu-24.04\home\<you>\mlops` UNC path.
- **Kind has no native GPU**: use `nvkind` + `nvidia-container-toolkit` CDI for Docker if you need GPU in local K8s (M4).