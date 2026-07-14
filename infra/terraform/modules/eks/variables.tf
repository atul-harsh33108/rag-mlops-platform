variable "cluster_name" {
  type        = string
  description = "EKS cluster name."
}
variable "kubernetes_version" {
  type        = string
  default     = "1.33"
  description = "EKS Kubernetes version."
}
variable "region" {
  type        = string
  description = "AWS region (for IRSA policies + SecretStore)."
}
variable "vpc_id" {
  type = string
}
variable "subnet_ids" {
  type        = list(string)
  description = "Private + public subnet ids for the EKS control plane + managed nodes."
}
variable "endpoint_public_access_cidrs" {
  type        = list(string)
  default     = ["0.0.0.0/0"]
  description = "CIDRs allowed to reach the public API endpoint (lock down to corp egress in prod)."
}
variable "enable_karpenter" {
  type    = bool
  default = true
}
variable "access_entries" {
  type    = any
  default = {}
  description = "Map of access entries (replaces aws-auth). CI OIDC role + engineers → system:masters."
}
variable "system_node_min_size" {
  type    = number
  default = 2
}
variable "system_node_max_size" {
  type    = number
  default = 4
}
variable "system_node_desired_size" {
  type    = number
  default = 2
}
variable "langfuse_db_host" {
  type        = string
  default     = ""
  description = "Langfuse Postgres host (for Grafana datasource)."
}
variable "grafana_admin_password" {
  type        = string
  sensitive   = true
  description = "Grafana admin password."
}
variable "tags" {
  type    = map(string)
  default = {}
}