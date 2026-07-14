# EKS module (M5) — the cluster + Karpenter + cluster-essential add-ons. Uses
# terraform-aws-modules/eks/aws v21.x: `kubernetes_version` (renamed from cluster_version),
# Access Entries (replaces the aws-auth ConfigMap), built-in Karpenter enablement.
#
# Add-ons provisioned here via Helm (Helm provider boots the cluster, then Argo CD takes over
# the app layer — this module only owns cluster-essential infra that Argo can't self-host):
#   - aws-load-balancer-controller (ALB/NLB)
#   - external-secrets             (pulls DB/Clerk secrets from Secrets Manager into K8s)
#   - mountpoint-s3-csi-driver     (vLLM reads model weights from S3 as a ReadOnlyMany PV)
#   - kube-prometheus-stack        (Prometheus + Grafana + Alertmanager)
#   - loki                         (log aggregation)
#   - argo-cd                      (GitOps for the app layer)

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.14"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  cluster_name                       = var.cluster_name
  kubernetes_version                 = var.kubernetes_version
  cluster_endpoint_public_access     = true
  cluster_endpoint_public_access_cidrs = var.endpoint_public_access_cidrs
  cluster_enabled_log_types          = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  cluster_encryption_config          = { resources = ["secrets"] }
  create_cloudwatch_log_group        = true

  vpc_id      = var.vpc_id
  subnet_ids  = var.subnet_ids

  # IRSA + EKS Pod Identity for add-ons.
  enable_irsa = true
  enable_eks_pod_identity = true

  # EKS managed add-ons. v21 uses a map with `most_recent`.
  cluster_addons = {
    vpc_cni = { most_recent = true }
    coredns = { most_recent = true }
    kube_proxy = { most_recent = true }
    aws_ebs_csi_driver = { most_recent = true }
  }

  # Karpenter — installed + IRSA-wired by the module; NodePool/NodeClass created in karpenter.tf.
  enable_karpenter = var.enable_karpenter
  karpenter = {
    node_name                = "karpenter-nodes"
    node_role_name           = "${var.cluster_name}-karpenter-node"
    node_role_managed_policies = ["arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSWorkerNodePolicy"]
  }

  # Access Entries (replaces aws-auth ConfigMap). CI OIDC role + dev engineers get
  # system:masters; the deploy role gets a scoped group for GitOps.
  access_entries = var.access_entries

  # A small managed node group for the add-ons themselves (Karpenter, ALB controller, Argo,
  # Prometheus) — these must run BEFORE Karpenter can provision GPU nodes.
  eks_managed_node_groups = {
    system = {
      instance_types = ["t4g.medium"] # Graviton, cheap control-plane-ish nodes
      min_size       = var.system_node_min_size
      max_size       = var.system_node_max_size
      desired_size   = var.system_node_desired_size
      disk_size      = 50
    }
  }

  tags = merge(var.tags, { "karpenter.sh/discovery" = var.cluster_name })
}

# kubectl + helm + kubernetes providers, wired to the new cluster.
provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
  load_config_file       = false
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}