{{/* alembic upgrade head до установки/обновления подов сервиса */}}
{{- define "service-lib.migrations" -}}
{{- if .Values.migrations.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "service-lib.name" . }}-migrate
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
    app.kubernetes.io/component: migrations
  annotations:
    helm.sh/hook: pre-install,pre-upgrade
    helm.sh/hook-weight: "0"
    helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded
spec:
  backoffLimit: 10
  activeDeadlineSeconds: 600
  template:
    metadata:
      labels:
        {{- include "service-lib.selector" . | nindent 8 }}
        app.kubernetes.io/component: migrations
    spec:
      restartPolicy: OnFailure
      automountServiceAccountToken: false
      securityContext:
        {{- include "service-lib.podSecurityContext" . | nindent 8 }}
      containers:
        - name: migrate
          image: {{ include "service-lib.image" . }}
          imagePullPolicy: IfNotPresent
          command: ["alembic", "upgrade", "head"]
          env:
            {{- include "service-lib.env" . | nindent 12 }}
          resources:
            requests: { cpu: 50m, memory: 96Mi }
            limits: { memory: 256Mi }
          securityContext:
            {{- include "service-lib.containerSecurityContext" . | nindent 12 }}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
{{- end }}
{{- end }}
