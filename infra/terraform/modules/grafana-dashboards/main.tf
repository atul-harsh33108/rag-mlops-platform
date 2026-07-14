# Grafana dashboards + Prometheus alert rules (M5). The dashboard JSON is shipped as a ConfigMap
# that kube-prometheus-stack's Grafana sidecar auto-imports (sidecar.dashboards.enabled must be
# true — set on the kube-prometheus helm release in the eks module). Alert rules ship as a
# PrometheusRule CR that the kube-prometheus Prometheus picks up.
#
# Dashboard queries two datasources:
#   - Prometheus (uid "prometheus", provisioned by kube-prometheus-stack) — request rate, latency
#     heatmap, error rate. Requires the app to expose rag_chat_* + rag_no_info_total metrics.
#   - Langfuse Postgres (uid "Langfuse", provisioned in eks module) — cost per turn, slowest
#     traces. A read-only grafana_reader role is created at the env level.

terraform {
  required_version = ">= 1.9.0"
  required_providers {
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.14"
    }
  }
}

# Dashboard ConfigMap — discovered by the Grafana sidecar via the label.
resource "kubectl_manifest" "dashboard" {
  yaml_body = yamlencode({
    apiVersion = "v1"
    kind       = "ConfigMap"
    metadata = {
      name      = "rag-overview-dashboard"
      namespace = var.namespace
      labels = {
        "grafana_dashboard" = "1"
      }
    }
    data = {
      "rag-overview.json" = file("${path.module}/dashboards/rag-overview.json")
    }
  })
}

# Alert rules (PrometheusRule). Thresholds from the M5 plan:
#   - p95 > 8s for 5m          → rag latency regression
#   - error rate > 5% for 5m   → availability
#   - LLM spend > $2/h          → cost runaway
#   - "no info" > 25% for 15m  → grounding collapse (RAG returning abstains)
#   - confidence drop           → sampled-eval regression (M7 wires the metric; placeholder here)
resource "kubectl_manifest" "alerts" {
  yaml_body = yamlencode({
    apiVersion = "monitoring.coreos.com/v1"
    kind       = "PrometheusRule"
    metadata = {
      name      = "rag-alerts"
      namespace = var.namespace
      labels = {
        "prometheus" = "kube-prometheus-stack-prometheus"
        "release"    = "kube-prometheus-stack"
      }
    }
    spec = {
      groups = [
        {
          name = "rag.latency"
          rules = [
            {
              alert = "RagP95LatencyHigh"
              expr  = "histogram_quantile(0.95, sum(rate(rag_chat_duration_seconds_bucket[5m])) by (le)) > 8"
              for   = "5m"
              labels = { severity = "warning" }
              annotations = { summary = "RAG p95 latency > 8s for 5m" }
            },
          ]
        },
        {
          name = "rag.availability"
          rules = [
            {
              alert = "RagErrorRateHigh"
              expr  = "sum(rate(rag_chat_requests_total{status=\"error\"}[5m])) / clamp_min(sum(rate(rag_chat_requests_total[5m])), 1e-9) > 0.05"
              for   = "5m"
              labels = { severity = "critical" }
              annotations = { summary = "RAG error rate > 5%" }
            },
            {
              alert = "RagNoInfoHigh"
              expr  = "sum(rate(rag_no_info_total[15m])) / clamp_min(sum(rate(rag_chat_requests_total[15m])), 1e-9) > 0.25"
              for   = "15m"
              labels = { severity = "warning" }
              annotations = { summary = "RAG 'I don't have enough info' rate > 25% for 15m (grounding collapse)" }
            },
          ]
        },
        {
          name = "rag.cost"
          rules = [
            {
              alert = "RagSpendHigh"
              expr  = "sum(rate(rag_llm_cost_usd[1h])) * 3600 > 2"
              for   = "10m"
              labels = { severity = "warning" }
              annotations = { summary = "LLM spend > $2/h" }
            },
          ]
        },
      ]
    }
  })
}