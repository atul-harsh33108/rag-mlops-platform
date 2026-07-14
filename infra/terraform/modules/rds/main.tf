# RDS Postgres — the shared metadata store (app tenants + corpus_state + LiteLLM spend logs +
# API keys). Multi-AZ for prod; single-AZ for dev. The app + LiteLLM + Airflow connect to this
# via the secretmanager-stored connection string (External Secrets → K8s Secret).
#
# Connection string is written to AWS Secrets Manager (not output in plaintext). The K8s side
# reads it via External Secrets Operator + IRSA (no static keys).

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

resource "random_password" "db" {
  length  = 32
  special = false
}

module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"

  identifier        = var.name
  engine            = "postgres"
  engine_version    = "16.4"
  instance_class    = var.instance_class

  allocated_storage = var.allocated_storage
  storage_encrypted = true

  db_name                = var.db_name
  username               = var.db_user
  manage_master_user_password = false
  password               = random_password.db.result
  multi_az               = var.multi_az
  storage_type           = "gp3"
  backup_retention_period = var.multi_az ? 14 : 1
  deletion_protection    = var.deletion_protection

  vpc_id               = var.vpc_id
  subnet_ids           = var.subnet_ids
  create_db_subnet_group = true

  # Security group: ingress 5432 from the EKS node SG + the EKS security group.
  create_db_security_group = true
  allowed_security_groups  = var.allowed_security_groups

  maintenance_window         = "Mon:00:00-Mon:03:00"
  backup_window              = "03:00-06:00"
  skip_final_snapshot        = !var.deletion_protection
  final_snapshot_identifier  = "${var.name}-final"
  tags                       = var.tags
}

# Store the full connection URL in Secrets Manager for External Secrets to pick up.
resource "aws_secretsmanager_secret" "db_url" {
  name                    = "/mlops/${var.name}/database_url"
  recovery_window_in_days = var.deletion_protection ? 30 : 0
  kms_key_id              = aws_kms_key.db.arn
}

resource "aws_kms_key" "db" {
  description             = "KMS key for ${var.name} DB secret"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = "postgresql+psycopg://${var.db_user}:${urlencode(random_password.db.result)}@${module.db.db_instance_address}:5432/${var.db_name}"
}