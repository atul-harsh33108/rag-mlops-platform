# Prod env — composes the M5 modules into an EKS production cluster. Flow:
#   vpc -> eks (cluster + Karpenter + add-ons) -> rds (metadata, allowed SG = eks cluster SG)
#        -> s3 (models/mlflow/langfuse) + ecr (image repos)
#        -> IRSA roles (app: mlflow artifacts; vllm: model weights; langfuse: blobs)
#        -> grafana dashboards + alert rules (kubectl, provider from the eks module)
#        -> ExternalSecret (DB URL -> K8s Secret for the app)
#        -> GitHub OIDC role for CI (push to ECR; no static keys)

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

# --- VPC ---
module "vpc" {
  source        = "../../modules/vpc"
  name          = var.cluster_name
  cidr          = "10.0.0.0/16"
  azs           = var.azs
  private_subnets  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets   = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
  database_subnets = ["10.0.201.0/24", "10.0.202.0/24", "10.0.203.0/24"]
  cluster_name  = var.cluster_name
  single_nat_gateway = false # one NAT per AZ for prod HA
}

# --- EKS (cluster + Karpenter + add-ons) ---
module "eks" {
  source = "../../modules/eks"

  cluster_name          = var.cluster_name
  kubernetes_version    = var.kubernetes_version
  region                = var.region
  vpc_id                = module.vpc.vpc_id
  subnet_ids            = concat(module.vpc.private_subnet_ids, module.vpc.public_subnet_ids)
  enable_karpenter      = true
  langfuse_db_host      = var.langfuse_db_host
  grafana_admin_password = var.grafana_admin_password

  # Access entries: CI deploy role + engineers get system:masters. The CI role ARN is created
  # below; reference its ARN here (Terraform resolves the dependency).
  access_entries = {
    ci = {
      principal_arn     = aws_iam_role.ci_deploy.arn
      kubernetes_username = "ci-deploy"
      policy_associations = { admin = { policy_arn = "arn:${local.partition}:eks:${var.region}:${local.account_id}:cluster/${var.cluster_name}" } }
    }
  }

  system_node_min_size     = 3
  system_node_max_size     = 6
  system_node_desired_size = 3
  tags = var.tags
}

# --- RDS (app metadata) — allowed SG = EKS cluster SG so pods can reach it ---
module "rds" {
  source = "../../modules/rds"
  name   = "${var.cluster_name}-meta"
  instance_class       = "db.r7g.large" # prod: x-large if heavy LiteLLM spend logging
  allocated_storage     = 100
  multi_az              = true
  deletion_protection   = true
  vpc_id                = module.vpc.vpc_id
  subnet_ids            = module.vpc.database_subnet_ids
  allowed_security_groups = [module.eks.cluster_security_group_id]
  tags                  = var.tags
}

# --- S3 (models / mlflow / langfuse) ---
module "s3" {
  source          = "../../modules/s3-bucket"
  models_bucket   = var.models_bucket
  mlflow_bucket   = var.mlflow_bucket
  langfuse_bucket = var.langfuse_bucket
  tags            = var.tags
}

# --- ECR (image repos) ---
module "ecr" {
  source      = "../../modules/ecr"
  prefix      = var.repo_prefix
  repo_names  = ["app", "pipelines", "ui"]
  tags        = var.tags
}

# --- IAM policies for IRSA roles ---
data "aws_iam_policy_document" "app_s3" {
  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      "arn:${local.partition}:s3:::${var.mlflow_bucket}",
      "arn:${local.partition}:s3:::${var.mlflow_bucket}/*",
    ]
  }
}
resource "aws_iam_policy" "app_s3" {
  name   = "${var.cluster_name}-app-s3"
  policy = data.aws_iam_policy_document.app_s3.json
}

data "aws_iam_policy_document" "vllm_s3" {
  statement {
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:${local.partition}:s3:::${var.models_bucket}",
      "arn:${local.partition}:s3:::${var.models_bucket}/*",
    ]
  }
}
resource "aws_iam_policy" "vllm_s3" {
  name   = "${var.cluster_name}-vllm-s3"
  policy = data.aws_iam_policy_document.vllm_s3.json
}

data "aws_iam_policy_document" "langfuse_s3" {
  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      "arn:${local.partition}:s3:::${var.langfuse_bucket}",
      "arn:${local.partition}:s3:::${var.langfuse_bucket}/*",
    ]
  }
}
resource "aws_iam_policy" "langfuse_s3" {
  name   = "${var.cluster_name}-langfuse-s3"
  policy = data.aws_iam_policy_document.langfuse_s3.json
}

# --- IRSA roles (no static keys) ---
module "app_irsa" {
  source              = "../../modules/irsa"
  name                = "app"
  oidc_issuer_url     = module.eks.oidc_provider
  k8s_service_account = "app-sa"
  k8s_namespace       = "mlops"
  policy_arns         = [aws_iam_policy.app_s3.arn]
}
module "vllm_irsa" {
  source              = "../../modules/irsa"
  name                = "vllm"
  oidc_issuer_url     = module.eks.oidc_provider
  k8s_service_account = "vllm-sa"
  k8s_namespace       = "mlops"
  policy_arns         = [aws_iam_policy.vllm_s3.arn]
}
module "langfuse_irsa" {
  source              = "../../modules/irsa"
  name                = "langfuse"
  oidc_issuer_url     = module.eks.oidc_provider
  k8s_service_account = "langfuse-sa"
  k8s_namespace       = "mlops"
  policy_arns         = [aws_iam_policy.langfuse_s3.arn]
}

# --- grafana dashboards + alert rules (kubectl provider comes from the eks module) ---
module "grafana" {
  source    = "../../modules/grafana-dashboards"
  namespace = "monitoring"
  depends_on = [module.eks]
}

# --- ExternalSecret: pull DATABASE_URL from Secrets Manager into a K8s Secret for the app ---
resource "kubectl_manifest" "db_url_secret" {
  yaml_body = yamlencode({
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata = { name = "app-db-url", namespace = "mlops" }
    spec = {
      secretStoreRef = { name = "aws-sm", kind = "ClusterSecretStore" }
      target = { name = "app-db-url", creationPolicy = "Owner" }
      data = [{
        secretKey = "DATABASE_URL"
        remoteRef = { key = module.rds.db_secret_name }
      }]
    }
  })
  depends_on = [module.eks, module.rds]
}

# --- GitHub OIDC role for CI (push to ECR; no static keys) ---
data "aws_iam_policy_document" "ci_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main", "repo:${var.github_repo}:pull_request"]
    }
  }
}

data "aws_iam_policy_document" "ci_ecr" {
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
      "ecr:GetAuthorizationToken", "ecr:BatchGetImage",
      "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
    ]
    resources = concat(
      [for r in module.ecr.repository_arns : r],
      ["arn:${local.partition}:ecr:${var.region}:${local.account_id}:repository/${var.repo_prefix}/*"],
    )
    # GetAuthorizationToken requires resource "*", so split it out.
  }
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "ci_deploy" {
  name               = "${var.cluster_name}-ci-deploy"
  assume_role_policy = data.aws_iam_policy_document.ci_assume.json
}

resource "aws_iam_policy" "ci_ecr" {
  name   = "${var.cluster_name}-ci-ecr"
  policy = data.aws_iam_policy_document.ci_ecr.json
}

resource "aws_iam_role_policy_attachment" "ci_ecr" {
  role       = aws_iam_role.ci_deploy.name
  policy_arn = aws_iam_policy.ci_ecr.arn
}