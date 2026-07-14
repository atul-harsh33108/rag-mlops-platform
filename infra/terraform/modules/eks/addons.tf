# Cluster-essential add-ons (Helm). Argo CD owns the app layer; this module owns infra add-ons
# that Argo can't self-host (the ALB controller, External Secrets, Mountpoint CSI, the
# observability stack). Each add-on that talks to AWS gets its own IRSA role — no static keys.

# --- aws-load-balancer-controller (ALB for HTTP, NLB for vLLM/TEI) ---
resource "helm_release" "alb_controller" {
  name             = "aws-load-balancer-controller"
  repository       = "https://aws.github.io/eks-charts"
  chart            = "aws-load-balancer-controller"
  version          = "1.11.0"
  namespace        = "kube-system"
  create_namespace = false
  wait             = false

  values = [yamlencode({
    clusterName  = var.cluster_name
    vpcId        = var.vpc_id
    serviceAccount = {
      create = true
      name   = "aws-load-balancer-controller"
      annotations = {
        "eks.amazonaws.com/role-arn" = aws_iam_role.alb_controller.arn
      }
    }
  })]
  depends_on = [module.eks]
}

data "aws_iam_policy_document" "alb_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${module.eks.oidc_provider}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

# The ALB controller needs a broad policy; use the AWS-managed one for simplicity.
resource "aws_iam_role" "alb_controller" {
  name               = "${var.cluster_name}-alb-controller"
  assume_role_policy = data.aws_iam_policy_document.alb_assume.json
}

resource "aws_iam_role_policy_attachment" "alb_controller" {
  role       = aws_iam_role.alb_controller.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSLoadBalancerControllerIAMRole"
}

# --- external-secrets (pulls Secrets Manager → K8s Secret; IRSA reads the secret) ---
# IRSA role for the external-secrets controller: read-only on Secrets Manager under /mlops/*.
data "aws_iam_policy_document" "es_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${module.eks.oidc_provider}"]
    }
    condition {
      test = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values = ["system:serviceaccount:external-secrets:external-secrets"]
    }
  }
}

data "aws_iam_policy_document" "es_perms" {
  statement {
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["arn:${data.aws_partition.current.partition}:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:/mlops/*"]
  }
}

resource "aws_iam_role" "external_secrets" {
  name               = "${var.cluster_name}-external-secrets"
  assume_role_policy = data.aws_iam_policy_document.es_assume.json
}

resource "aws_iam_policy" "external_secrets" {
  name   = "${var.cluster_name}-external-secrets"
  policy = data.aws_iam_policy_document.es_perms.json
}

resource "aws_iam_role_policy_attachment" "external_secrets" {
  role       = aws_iam_role.external_secrets.name
  policy_arn = aws_iam_policy.external_secrets.arn
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = "0.13.x"
  namespace        = "external-secrets"
  create_namespace = true
  wait             = false

  values = [yamlencode({
    serviceAccount = {
      create = false
      name   = "external-secrets"
      annotations = { "eks.amazonaws.com/role-arn" = aws_iam_role.external_secrets.arn }
    }
  })]
  depends_on = [module.eks]
}

# SecretStore: points External Secrets at AWS Secrets Manager in this account/region. The
# IRSA role for external-secrets gets secretsmanager read on the secrets we create.
resource "kubectl_manifest" "cluster_secret_store" {
  yaml_body = yamlencode({
    apiVersion = "external-secrets.io/v1"
    kind       = "ClusterSecretStore"
    metadata   = { name = "aws-sm" }
    spec = {
      provider = {
        aws = {
          service = "SecretsManager"
          region  = var.region
          auth = { jwt = { serviceAccountRef = { name = "external-secrets", namespace = "external-secrets" } } }
        }
      }
    }
  })
  depends_on = [helm_release.external_secrets]
}

# --- mountpoint-s3-csi-driver (vLLM reads model weights from S3 as a ReadOnlyMany PV) ---
resource "helm_release" "mountpoint" {
  name       = "mountpoint-s3-csi"
  repository = "https://awslabs.github.io/mountpoint-s3-csi-driver"
  chart      = "aws-mountpoint-s3-csi-driver"
  version    = "1.x"
  namespace  = "kube-system"
  wait       = false
  depends_on = [module.eks]
}

# --- kube-prometheus-stack (Prometheus + Grafana + Alertmanager) ---
resource "helm_release" "kube_prometheus" {
  name             = "kube-prometheus-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  version          = "75.x"
  namespace        = "monitoring"
  create_namespace = true
  wait             = false

  values = [
    yamlencode({
      alertmanager = { enabled = true }
      grafana = {
        enabled = true
        adminPassword = var.grafana_admin_password
        # Auto-import dashboards from ConfigMaps labeled grafana_dashboard=1 (the
        # grafana-dashboards module ships the RAG overview that way).
        sidecar = {
          dashboards = {
            enabled        = true
            label          = "grafana_dashboard"
            labelValue     = "1"
            searchNamespace = "monitoring"
          }
        }
        # Langfuse as a Postgres data source (read-only grafana_reader role created in the env).
        # Credentials (LANGFUSE_READER_USER/PASS) come from a K8s Secret the env provisions via
        # External Secrets; grafana resolves $${...} from env injected by that secret.
        datasources = {
          "datasources.yaml" = {
            apiVersion = 1
            datasources = [{
              name      = "Langfuse"
              type      = "postgres"
              uid       = "Langfuse"
              url       = var.langfuse_db_host
              database  = "langfuse"
              user      = "$${LANGFUSE_READER_USER}"
              secureJsonData = { password = "$${LANGFUSE_READER_PASS}" }
              jsonData = { sslmode = "disable", postgresVersion = 1600 }
            }]
          }
        }
      }
      prometheus = {
        prometheusSpec = {
          retention = "30d"
          storageSpec = {
            volumeClaimTemplate = {
              spec = {
                storageClassName = "gp3"
                resources = { requests = { storage = "50Gi" } }
              }
            }
          }
        }
      }
    }),
    fileexists("${path.module}/grafana-values.yaml") ? file("${path.module}/grafana-values.yaml") : "",
  ]
  depends_on = [module.eks]
}

# --- loki (log aggregation, Grafana sidecar auto-discovers it) ---
resource "helm_release" "loki" {
  name             = "loki"
  repository       = "https://grafana.github.io/helm-charts"
  chart            = "loki"
  version          = "6.x"
  namespace        = "monitoring"
  create_namespace = true
  wait             = false
  values = [yamlencode({
    deploymentMode = "SingleGriffin" # single-binary for simplicity; scale to SimpleScalable prod
    loki = { commonConfig = { replication_factor = 1 } }
  })]
  depends_on = [module.eks]
}

# --- argo-cd (GitOps for the app layer; apps defined in infra/k8s-bootstrap/argocd-apps.yaml) ---
resource "helm_release" "argocd" {
  name             = "argo-cd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "9.5.0"
  namespace        = "argocd"
  create_namespace = true
  wait             = false
  values = [yamlencode({
    configs = { cm = { "application.instanceLabelKey" = "app.kubernetes.io/instance" } }
  })]
  depends_on = [module.eks]
}