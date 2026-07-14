variable "name" {
  type        = string
  description = "VPC name."
}

variable "cidr" {
  type        = string
  description = "VPC CIDR."
}

variable "azs" {
  type        = list(string)
  description = "Availability zones (>=2 for HA)."
}

variable "private_subnets" {
  type        = list(string)
  description = "Private subnet CIDRs (EKS worker nodes)."
}

variable "public_subnets" {
  type        = list(string)
  description = "Public subnet CIDRs (ALB/NLB)."
}

variable "database_subnets" {
  type        = list(string)
  description = "Database subnet CIDRs (RDS)."
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster name (for subnet tagging)."
}

variable "single_nat_gateway" {
  type        = bool
  default     = true
  description = "Single NAT gateway (dev) vs one-per-AZ (prod HA)."
}