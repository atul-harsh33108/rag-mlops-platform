output "db_instance_address" {
  value       = module.db.db_instance_address
  description = "RDS endpoint hostname."
}
output "db_secret_arn" {
  value       = aws_secretsmanager_secret.db_url.arn
  description = "Secrets Manager secret ARN holding the full DATABASE_URL (for External Secrets)."
}
output "db_secret_name" {
  value       = aws_secretsmanager_secret.db_url.name
  description = "Secrets Manager secret name (External Secrets references by name)."
}
output "db_security_group_id" {
  value       = try(module.db.db_instance_security_group_id, null)
  description = "RDS security group id (best-effort; depends on module version)."
}