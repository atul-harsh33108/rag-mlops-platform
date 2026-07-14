variable "region" {
  type    = string
  default = "us-east-1"
}
variable "azs" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}
variable "cluster_name" {
  type    = string
  default = "mlops-prod"
}
variable "kubernetes_version" {
  type    = string
  default = "1.33"
}
variable "repo_prefix" {
  type    = string
  default = "mlops"
}
variable "models_bucket"   { type = string }
variable "mlflow_bucket"   { type = string }
variable "langfuse_bucket" { type = string }

variable "grafana_admin_password" {
  type      = string
  sensitive = true
}
# CI OIDC: the GitHub repo allowed to assume the deploy role (org/repo, e.g. "acme/rag-mlops").
variable "github_repo" {
  type    = string
  default = "acme/rag-mlops"
}
# Langfuse in-cluster Postgres host for the Grafana datasource (Langfuse ships its own
# bundled Postgres via the umbrella chart; this is its in-cluster service DNS).
variable "langfuse_db_host" {
  type    = string
  default = "langfuse-postgres.mlops.svc.cluster.local:5432"
}
variable "tags" {
  type    = map(string)
  default = { env = "prod", project = "mlops" }
}