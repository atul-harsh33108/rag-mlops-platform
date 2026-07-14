variable "region" { type = string; default = "us-east-1" }
variable "azs" { type = list(string); default = ["us-east-1a", "us-east-1b"] }
variable "cluster_name" { type = string; default = "mlops-dev" }
variable "kubernetes_version" { type = string; default = "1.33" }
variable "repo_prefix" { type = string; default = "mlops" }
variable "models_bucket"   { type = string }
variable "mlflow_bucket"   { type = string }
variable "langfuse_bucket" { type = string }
variable "grafana_admin_password" { type = string; sensitive = true }
variable "github_repo" { type = string; default = "acme/rag-mlops" }
variable "langfuse_db_host" { type = string; default = "langfuse-postgres.mlops.svc.cluster.local:5432" }
variable "tags" { type = map(string); default = { env = "dev", project = "mlops" } }