{{/* Только если в кластере есть Prometheus Operator (kube-prometheus-stack) */}}
{{- define "service-lib.servicemonitor" -}}
{{- if and .Values.serviceMonitor.enabled (.Capabilities.APIVersions.Has "monitoring.coreos.com/v1") }}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "service-lib.name" . }}
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- include "service-lib.selector" . | nindent 6 }}
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
{{- end }}
{{- end }}
