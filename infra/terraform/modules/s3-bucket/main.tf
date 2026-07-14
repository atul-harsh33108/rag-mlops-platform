# S3 buckets for M5:
#   - model weights (vLLM reads via Mountpoint CSI, ReadOnlyMany PV — ~95% cheaper than EBS)
#   - MLflow artifacts
#   - Langfuse blobs (S3 event storage backend)
#   - TF state is a SEPARATE bucket declared in backend.tf (not here — Terraform can't manage
#     its own state bucket cleanly mid-init; create it out-of-band or via a bootstrap run).
#
# Encryption + versioning + public-access-block + lifecycle (transition to IA after 30d,
# Glacier after 90d for artifacts/blobs) on every bucket.

terraform {
  required_version = ">= 1.9.0"
}

module "models" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "~> 4.0"

  bucket                  = var.models_bucket
  force_destroy           = false
  versioning              = { enabled = true }
  block_public_account_settings = true
  server_side_encryption_configuration = {
    rule = { apply_server_side_encryption_by_default = { sse_algorithm = "aws:kms" } }
  }
  lifecycle_rules = [{
    id      = "models-transition"
    enabled = true
    transitions = [{ days = 30, storage_class = "STANDARD_IA" }]
  }]
  tags = var.tags
}

module "mlflow" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "~> 4.0"

  bucket                  = var.mlflow_bucket
  force_destroy           = false
  versioning              = { enabled = true }
  block_public_account_settings = true
  server_side_encryption_configuration = {
    rule = { apply_server_side_encryption_by_default = { sse_algorithm = "aws:kms" } }
  }
  lifecycle_rules = [{
    id      = "mlflow-transition"
    enabled = true
    transitions = [
      { days = 30, storage_class = "STANDARD_IA" },
      { days = 90, storage_class = "GLACIER" },
    ]
  }]
  tags = var.tags
}

module "langfuse" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "~> 4.0"

  bucket                  = var.langfuse_bucket
  force_destroy           = false
  versioning              = { enabled = true }
  block_public_account_settings = true
  server_side_encryption_configuration = {
    rule = { apply_server_side_encryption_by_default = { sse_algorithm = "aws:kms" } }
  }
  lifecycle_rules = [{
    id      = "langfuse-transition"
    enabled = true
    transitions = [{ days = 30, storage_class = "STANDARD_IA" }]
  }]
  tags = var.tags
}