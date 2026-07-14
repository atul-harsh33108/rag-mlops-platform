{{/* Umbrella-level helpers. */}}
{{- define "mlops.fullname" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "mlops.namespace" -}}
{{- .Values.namespace | default "mlops" -}}
{{- end -}}