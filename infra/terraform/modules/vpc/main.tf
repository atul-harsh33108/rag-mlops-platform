# VPC module — thin wrapper over terraform-aws-modules/vpc/aws. EKS needs a VPC with the
# right tags for the ALB/NLB controllers and subnets across >=2 AZs for HA.
#
# Tags `kubernetes.io/role/elb` + `kubernetes.io/cluster/<name>` are REQUIRED for the AWS
# Load Balancer Controller to discover subnets (missing tags → ALB creation hangs ~10min).

terraform {
  required_version = ">= 1.9.0"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = var.name
  cidr = var.cidr

  azs              = var.azs
  private_subnets  = var.private_subnets
  public_subnets   = var.public_subnets
  database_subnets = var.database_subnets

  # NAT: single gateway is cheaper for dev; one-per-AZ for prod (var.single_nat_gateway).
  enable_nat_gateway   = true
  single_nat_gateway    = var.single_nat_gateway
  enable_dns_hostnames  = true
  enable_dns_support   = true

  # EKS cluster + ALB/NLB subnet discovery tags.
  enable_cluster_tags     = true
  cluster_name            = var.cluster_name
  public_subnet_tags     = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags    = { "kubernetes.io/role/internal-elb" = 1 }
  database_subnet_tags   = { "kubernetes.io/role/internal-elb" = 1 }

  create_database_subnet_route_table = true
}