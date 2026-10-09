{{- define "service-lib.name" -}}
{{- .Chart.Name -}}
{{- end }}

{{- define "service-lib.labels" -}}
app.kubernetes.io/name: {{ include "service-lib.name" . }}
app.kubernetes.io/part-of: orders-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ include "service-lib.tag" . | quote }}
{{- end }}

{{- define "service-lib.selector" -}}
app.kubernetes.io/name: {{ include "service-lib.name" . }}
{{- end }}

{{- define "service-lib.tag" -}}
{{- .Values.image.tag | default .Values.global.image.tag -}}
{{- end }}

{{- define "service-lib.image" -}}
{{ .Values.global.image.registry }}/orders-platform-{{ include "service-lib.name" . }}:{{ include "service-lib.tag" . }}
{{- end }}

{{/* Окружение контейнера: общие настройки → секреты → значения сервиса (могут ссылаться на секреты через $(VAR)) */}}
{{- define "service-lib.env" -}}
- name: ENVIRONMENT
  value: {{ .Values.global.environment | quote }}
- name: LOG_LEVEL
  value: {{ .Values.global.logLevel | quote }}
- name: KAFKA_BOOTSTRAP
  value: {{ .Values.global.kafkaBootstrap | quote }}
- name: SCHEMA_REGISTRY_URL
  value: {{ .Values.global.schemaRegistryUrl | quote }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.global.otlpEndpoint | quote }}
- name: PORT
  value: {{ .Values.port | quote }}
{{- range .Values.secretEnv }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.global.secretName }}
      key: {{ . }}
{{- end }}
- name: REDIS_URL
  value: "redis://:$(REDIS_PASSWORD)@redis:6379/0"
{{- range $name, $value := .Values.env }}
- name: {{ $name }}
  value: {{ $value | quote }}
{{- end }}
{{- end }}

{{- define "service-lib.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "service-lib.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}

{{/* Корневая ФС только для чтения: /tmp — отдельный emptyDir (heartbeat воркера, временные файлы) */}}
{{- define "service-lib.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- with .Values.volumeMounts }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "service-lib.volumes" -}}
- name: tmp
  emptyDir: {}
{{- with .Values.volumes }}
{{ toYaml . }}
{{- end }}
{{- end }}
