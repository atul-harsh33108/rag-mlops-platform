output "models_bucket"   { value = module.models.s3_bucket_id }
output "mlflow_bucket"   { value = module.mlflow.s3_bucket_id }
output "langfuse_bucket" { value = module.langfuse.s3_bucket_arn }
output "models_bucket_arn" { value = module.models.s3_bucket_arn }