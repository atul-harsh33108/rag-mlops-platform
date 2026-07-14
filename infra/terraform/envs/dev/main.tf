# Dev env — a cheaper, teardown-friendly EKS for staging/preview. Same modules as prod,
# smaller + single-AZ + no deletion protection (so `terraform destroy` is clean).
# See envs/prod/main.tf for the full HA/prod variant.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

module "vpc" {
  source             = "../../modules/vpc"
  name               = var.cluster_name
  cidr               = "10.10.0.0/16"
  azs                = var.azs
  private_subnets    = ["10.10.1.0/24", "10.10.2.0/24"]
  public_subnets     = ["10.10.101.0/24", "10.10.102.0/24"]
  database_subnets   = ["10.10.201.0/24", "10.10.202.0/24"]
  cluster_name       = var.cluster_name
  single_nat_gateway = true # dev: one NAT (cheaper)
}

module "eks" {
  source = "../../modules/eks"

  cluster_name           = var.cluster_name
  kubernetes_version     = var.kubernetes_version
  region                 = var.region
  vpc_id                 = module.vpc.vpc_id
  subnet_ids             = concat(module.vpc.private_subnet_ids, module.vpc.public_subnet_ids)
  enable_karpenter       = true
  langfuse_db_host       = var.langfuse_db_host
  grafana_admin_password = var.grafana_admin_password
  access_entries          = { ci = { principal_arn = aws_iam_role.ci_deploy.arn, kubernetes_username = "ci-deploy", policy_associations = { admin = { policy_arn = "arn:${local.partition}:eks:${var.region}:${local.account_id}:cluster/${var.cluster_name}" } } } }
  system_node_min_size     = 1
  system_node_max_size     = 3
  system_node_desired_size = 1
  tags = var.tags
}

module "rds" {
  source                = "../../modules/rds"
  name                  = "${var.cluster_name}-meta"
  instance_class        = "db.t4g.small" # dev: small + single-AZ
  allocated_storage      = 20
  multi_az               = false
  deletion_protection    = false # dev: destroyable
  vpc_id                 = module.vpc.vpc_id
  subnet_ids             = module.vpc.database_subnet_ids
  allowed_security_groups = [module.eks.cluster_security_group_id]
  tags                   = var.tags
}

module "s3" {
  source          = "../../modules/s3-bucket"
  models_bucket   = var.models_bucket
  mlflow_bucket   = var.mlflow_bucket
  langfuse_bucket = var.langfuse_bucket
  tags            = var.tags
}

module "ecr" {
  source     = "../../modules/ecr"
  prefix     = var.repo_prefix
  repo_names = ["app", "pipelines", "ui"]
  tags       = var.tags
}

# --- IRSA policies + roles (same scope as prod) ---
data "aws_iam_policy_document" "app_s3" {
  statement { actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = ["arn:${local.partition}:s3:::${var.mlflow_bucket}", "arn:${local.partition}:s3:::${var.mlflow_bucket}/*"] }
}
resource "aws_iam_policy" "app_s3" { name = "${var.cluster_name}-app-s3"; policy = data.aws_iam_policy_document.app_s3.json }

data "aws_iam_policy_document" "vllm_s3" {
  statement { actions = ["s3:GetObject", "s3:ListBucket"]
    resources = ["arn:${local.partition}:s3:::${var.models_bucket}", "arn:${local.partition}:s3:::${var.models_bucket}/*"] }
}
resource "aws_iam_policy" "vllm_s3" { name = "${var.cluster_name}-vllm-s3"; policy = data.aws_iam_policy_document.vllm_s3.json }

data "aws_iam_policy_document" "langfuse_s3" {
  statement { actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = ["arn:${local.partition}:s3:::${var.langfuse_bucket}", "arn:${local.partition}:s3:::${var.langfuse_bucket}/*"] }
}
resource "aws_iam_policy" "langfuse_s3" { name = "${var.cluster_name}-langfuse-s3"; policy = data.aws_iam_policy_document.langfuse_s3.json }

module "app_irsa"     { source = "../../modules/irsa"; name = "app"; oidc_issuer_url = module.eks.oidc_provider; k8s_service_account = "app-sa"; k8s_namespace = "mlops"; policy_arns = [aws_iam_policy.app_s3.arn] }
module "vllm_irsa"    { source = "../../modules/irsa"; name = "vllm"; oidc_issuer_url = module.eks.oidc_provider; k8s_service_account = "vllm-sa"; k8s_namespace = "mlops"; policy_arns = [aws_iam_policy.vllm_s3.arn] }
module "langfuse_irsa" { source = "../../modules/irsa"; name = "langfuse"; oidc_issuer_url = module.eks.oidc_provider; k8s_service_account = "langfuse-sa"; k8s_namespace = "mlops"; policy_arns = [aws_iam_policy.langfuse_s3.arn] }

module "grafana" {
  source     = "../../modules/grafana-dashboards"
  namespace  = "monitoring"
  depends_on = [module.eks]
}

resource "kubectl_manifest" "db_url_secret" {
  yaml_body = yamlencode({
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata   = { name = "app-db-url", namespace = "mlops" }
    spec = {
      secretStoreRef = { name = "aws-sm", kind = "ClusterSecretStore" }
      target         = { name = "app-db-url", creationPolicy = "Owner" }
      data = [{ secretKey = "DATABASE_URL", remoteRef = { key = module.rds.db_secret_name } }]
    }
  })
  depends_on = [module.eks, module.rds]
}

# --- CI OIDC role (same as prod; dev cluster) ---
data "aws_iam_policy_document" "ci_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals { type = "Federated"; identifiers = ["arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"] }
    condition { test = "StringEquals"; variable = "token.actions.githubusercontent.com:aud"; values = ["sts.amazonaws.com"] }
    condition { test = "StringLike"; variable = "token.actions.githubusercontent.com:sub"; values = ["repo:${var.github_repo}:ref:refs/heads/main", "repo:${var.github_repo}:pull_request"] }
  }
}
data "aws_iam_policy_document" "ci_ecr" {
  statement { actions = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload"]
    resources = concat([for r in module.ecr.repository_arns : r], ["arn:${local.partition}:ecr:${var.region}:${local.account_id}:repository/${var.repo_prefix}/*"]) }
  statement { actions = ["ecr:GetAuthorizationToken"]; resources = ["*"] }
}
resource "aws_iam_role" "ci_deploy" { name = "${var.cluster_name}-ci-deploy"; assume_role_policy = data.aws_iam_policy_document.ci_assume.json }
resource "aws_iam_policy" "ci_ecr" { name = "${var.cluster_name}-ci-ecr"; policy = data.aws_iam_policy_document.ci_ecr.json }
resource "aws_iam_role_policy_attachment" "ci_ecr" { role = aws_iam_role.ci_deploy.name; policy_arn = aws_iam_policy.ci_ecr.arn }