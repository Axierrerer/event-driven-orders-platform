{{/* Consumer'ы и outbox-relay: тот же образ, другая команда; без HTTP — проверка по heartbeat-файлу */}}
{{- define "service-lib.worker" -}}
{{- if .Values.worker.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "service-lib.name" . | trimSuffix "-service" }}-worker
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
    app.kubernetes.io/component: worker
spec:
  replicas: {{ .Values.worker.replicas }}
  revisionHistoryLimit: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      {{- include "service-lib.selector" . | nindent 6 }}
      app.kubernetes.io/component: worker
  template:
    metadata:
      labels:
        {{- include "service-lib.labels" . | nindent 8 }}
        app.kubernetes.io/component: worker
    spec:
      automountServiceAccountToken: false
      # SIGTERM: consumer коммитит offset и выходит, relay дописывает текущую пачку
      terminationGracePeriodSeconds: 30
      securityContext:
        {{- include "service-lib.podSecurityContext" . | nindent 8 }}
      containers:
        - name: worker
          image: {{ include "service-lib.image" . }}
          imagePullPolicy: IfNotPresent
          command: ["python", "-m", "src.worker"]
          env:
            {{- include "service-lib.env" . | nindent 12 }}
          livenessProbe:
            exec:
              command: ["python", "-m", "platform_lib.heartbeat", "/tmp/worker.alive", "60"]
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 5
          resources:
            {{- toYaml .Values.worker.resources | nindent 12 }}
          securityContext:
            {{- include "service-lib.containerSecurityContext" . | nindent 12 }}
          volumeMounts:
            {{- include "service-lib.volumeMounts" . | nindent 12 }}
      volumes:
        {{- include "service-lib.volumes" . | nindent 8 }}
{{- end }}
{{- end }}
