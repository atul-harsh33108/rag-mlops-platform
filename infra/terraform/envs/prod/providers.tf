terraform {
  required_version = ">= 1.9.0"

  # Backend: S3 + DynamoDB lock. The state bucket + lock table MUST be created out-of-band
  # first (Terraform can't bootstrap its own state bucket mid-init). See backend.tf.
  backend "s3" {
    bucket         = "mlops-tf-state-prod"
    key            = "mlops-prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mlops-tf-lock"
    encrypt        = true
  }

  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
    helm = { source = "hashicorp/helm", version = "~> 2.13" }
    kubectl = { source = "gavinbunney/kubectl", version = "~> 1.14" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.23" }
    random = { source = "hashicorp/random", version = "~> 3.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = var.tags }
}

# The k8s-native providers (helm/kubectl/kubernetes) are configured INSIDE the eks module,
# wired to the newly-created cluster. Env-level manifests that need kubectl use the eks
# module's provider via `providers = { kubectl = module.eks... }` — simplest is to declare a
# passthrough here that depends_on the cluster. (Terraform provider config can't read module
# outputs at provider-init time, so we delegate kubectl to the eks module and only use
# data-free resources here where possible.)