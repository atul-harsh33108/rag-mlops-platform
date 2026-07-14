terraform {
  required_version = ">= 1.9.0"

  backend "s3" {
    bucket         = "mlops-tf-state-dev"
    key            = "mlops-dev/terraform.tfstate"
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