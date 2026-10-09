{{/* Полный набор ресурсов сервиса — тонкие чарты сервисов вызывают только его */}}
{{- define "service-lib.all" -}}
{{ include "service-lib.api" . }}
{{- with (include "service-lib.worker" .) }}
---
{{ . }}
{{- end }}
{{- with (include "service-lib.migrations" .) }}
---
{{ . }}
{{- end }}
{{- with (include "service-lib.servicemonitor" .) }}
---
{{ . }}
{{- end }}
{{- end }}
