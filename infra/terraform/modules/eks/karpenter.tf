# Karpenter NodePool + EC2NodeClass. Two pools:
#   - gpu: g6e.xlarge (L4 24GB) for vLLM (Qwen3-14B AWQ) + TEI. Spot with a fallback to on-demand
#     so Spot interruption → Bifrost drains to Bedrock (handled by AWS Node Termination Handler
#     + LiteLLM fallback chain; see docs/decisions/bifrost-bedrock-vllm.md).
#   - cpu: t4g.medium for the app/api/gateway pods (cheaper than running them on the system group).
#
# GOTCHA: the first vLLM pod on a fresh Mountpoint PV takes 5-10min while it lazy-loads
# safetensors from S3. Pre-warm with a one-shot Job (kubectl apply in CI or a Helm hook) that
# `cat`s the safetensors index — otherwise Karpenter may mark the node unhealthy mid-load.

# The Karpenter CRDs are installed by the module's helm release; we wait via a null/delayed
# kubectl apply (Terraform can't natively wait for CRDs). `depends_on` the helm release.

resource "kubectl_manifest" "gpu_nodeclass" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata   = { name = "gpu" }
    spec = {
      amiFamily = "alinux2023"
      amiSelectorTerms = [{ alias = "al2023@latest" }]
      role     = module.eks.karpenter_node_role_name
      subnetSelectorTerms = [{
        tags = { "karpenter.sh/discovery" = var.cluster_name }
      }]
      securityGroupSelectorTerms = [{
        tags = { "karpenter.sh/discovery" = var.cluster_name }
      }]
      blockDeviceMappings = [{
        deviceName = "/dev/xvda"
        ebs = { volumeSize = "100Gi", volumeType = "gp3", encrypted = true }
      }]
    }
  })
  depends_on = [module.eks]
}

resource "kubectl_manifest" "gpu_nodepool" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "gpu" }
    spec = {
      template = {
        metadata = { labels = { pool = "gpu" } }
        spec = {
          nodeClassRef = { group = "karpenter.k8s.aws", kind = "EC2NodeClass", name = "gpu" }
          requirements = [
            { key = "karpenter.k8s.aws/instance-gpu-count", operator = "GreaterThan", values = ["0"] },
            { key = "karpenter.k8s.aws/instance-family", operator = "In", values = ["g6e", "g6"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["spot", "on-demand"] },
            { key = "karpenter.k8s.aws/instance-size", operator = "In", values = ["xlarge", "2xlarge"] },
          ]
          taints = [{ key = "nvidia.com/gpu", effect = "NoSchedule" }]
        }
      }
      limits   = { cpu = "64", memory = "256Gi" }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter     = "60s"
      }
    }
  })
  depends_on = [kubectl_manifest.gpu_nodeclass]
}

resource "kubectl_manifest" "cpu_nodeclass" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata   = { name = "cpu" }
    spec = {
      amiFamily = "alinux2023"
      amiSelectorTerms = [{ alias = "al2023@latest" }]
      role     = module.eks.karpenter_node_role_name
      subnetSelectorTerms = [{ tags = { "karpenter.sh/discovery" = var.cluster_name } }]
      securityGroupSelectorTerms = [{ tags = { "karpenter.sh/discovery" = var.cluster_name } }]
    }
  })
  depends_on = [module.eks]
}

resource "kubectl_manifest" "cpu_nodepool" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "cpu" }
    spec = {
      template = {
        spec = {
          nodeClassRef = { group = "karpenter.k8s.aws", kind = "EC2NodeClass", name = "cpu" }
          requirements = [
            { key = "karpenter.k8s.aws/instance-family", operator = "In", values = ["t4g", "c7g"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["spot", "on-demand"] },
          ]
        }
      }
      limits = { cpu = "32", memory = "64Gi" }
    }
  })
  depends_on = [kubectl_manifest.cpu_nodeclass]
}