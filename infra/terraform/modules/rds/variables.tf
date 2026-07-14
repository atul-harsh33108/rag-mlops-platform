variable "name" {
  type = string
}
variable "db_name" {
  type    = string
  default = "mlops"
}
variable "db_user" {
  type    = string
  default = "mlops"
}
variable "instance_class" {
  type    = string
  default = "db.t4g.medium" # arm-based Graviton, ~20% cheaper than x86
}
variable "allocated_storage" {
  type    = number
  default = 50
}
variable "multi_az" {
  type    = bool
  default = false
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "vpc_id" {
  type = string
}
variable "subnet_ids" {
  type = list(string)
}
variable "allowed_security_groups" {
  type    = list(string)
  default = []
}
variable "tags" {
  type    = map(string)
  default = {}
}