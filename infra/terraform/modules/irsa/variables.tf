variable "prefix" {
  type        = string
  default     = "mlops"
  description = "Role name prefix."
}
variable "name" {
  type        = string
  description = "Logical name (e.g. app, vllm, langfuse)."
}
variable "oidc_issuer_url" {
  type        = string
  description = "EKS OIDC issuer URL (module.eks.oidc_provider)."
}
variable "k8s_service_account" {
  type        = string
  description = "Kubernetes ServiceAccount name (created by the Helm chart)."
}
variable "k8s_namespace" {
  type        = string
  default     = "mlops"
}
variable "policy_arns" {
  type        = list(string)
  default     = []
  description = "Managed/custom policy ARNs to attach."
}
variable "tags" {
  type    = map(string)
  default = {}
}