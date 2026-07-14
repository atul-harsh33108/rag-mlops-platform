variable "models_bucket"   { type = string }
variable "mlflow_bucket"   { type = string }
variable "langfuse_bucket" { type = string }
variable "tags" {
  type    = map(string)
  default = {}
}