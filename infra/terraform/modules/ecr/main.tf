# ECR repos for the three images built in CI (app, pipelines, ui). Immutable tags disabled so
# `sha-<gitsha>` digest-pin promotion works (each commit gets a unique tag). Scan-on-push +
# image scanning config for Trivy/ECR scanning.

terraform {
  required_version = ">= 1.9.0"
}

resource "aws_ecr_repository" "this" {
  for_each             = toset(var.repo_names)
  name                 = "${var.prefix}/${each.value}"
  image_tag_mutability = "MUTABLE" # sha-<gitsha> tags are unique; mutable lets re-runs of a sha overwrite.
  encryption_configuration {
    encryption_type = "KMS"
  }
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = var.tags
}

# Lifecycle: keep the last N tags + untagged quarantine, expire old to bound cost.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each = toset(var.repo_names)
  repository = aws_ecr_repository.this[each.key].name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 100 tagged images"
        selection = {
          tagStatus     = "tagged"
          countType     = "imageCountMoreThan"
          countNumber   = 100
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countNumber = 7
          countUnit   = "days"
        }
        action = { type = "expire" }
      },
    ]
  })
}