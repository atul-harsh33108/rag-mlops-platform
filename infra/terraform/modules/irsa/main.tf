# IRSA — IAM Role for a Kubernetes ServiceAccount. The K8s ServiceAccount gets an EKS OIDC
# trust policy so pods assuming it receive short-lived AWS creds via the pod identity webhook.
# No static access keys ever live in the cluster (the M5 security posture).
#
# Usage:
#   module "app_irsa" {
#     source = "../modules/irsa"
#     name                = "app"
#     oidc_issuer_url     = module.eks.oidc_provider
#     k8s_service_account = "app-sa"      # SA created by the Helm chart
#     k8s_namespace        = "mlops"
#     policy_arns          = [aws_iam_policy.s3_models.arn]
#   }

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# Trust: the EKS OIDC issuer may assume this role ONLY for the named K8s SA in the named ns.
# The condition keys (aud + sub) bind the role to exactly one service account.
data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${var.oidc_issuer_url}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_issuer_url}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_issuer_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.prefix}-${var.name}-irsa"
  assume_role_policy = data.aws_iam_policy_document.trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = toset(var.policy_arns)
  role     = aws_iam_role.this.name
  policy_arn = each.value
}