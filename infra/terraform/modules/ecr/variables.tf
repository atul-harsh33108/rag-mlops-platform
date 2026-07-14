variable "prefix" {
  type        = string
  description = "Repo prefix (e.g. mlops)."
}

variable "repo_names" {
  type        = list(string)
  default     = ["app", "pipelines", "ui"]
  description = "ECR repo basenames."
}

variable "tags" {
  type    = map(string)
  default = {}
}