{{- define "service-lib.api" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "service-lib.name" . }}
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
    app.kubernetes.io/component: api
spec:
  {{- if not .Values.hpa.enabled }}
  replicas: {{ .Values.replicas }}
  {{- end }}
  revisionHistoryLimit: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      {{- include "service-lib.selector" . | nindent 6 }}
      app.kubernetes.io/component: api
  template:
    metadata:
      labels:
        {{- include "service-lib.labels" . | nindent 8 }}
        app.kubernetes.io/component: api
    spec:
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      securityContext:
        {{- include "service-lib.podSecurityContext" . | nindent 8 }}
      containers:
        - name: app
          image: {{ include "service-lib.image" . }}
          imagePullPolicy: IfNotPresent
          # Миграции выполняет отдельный Job (хук Helm), поэтому только uvicorn
          command:
            - uvicorn
            - src.main:create_app
            - --factory
            - --host=0.0.0.0
            - --port={{ .Values.port }}
            - --proxy-headers
            - --forwarded-allow-ips=*
            - --timeout-graceful-shutdown=20
          ports:
            - name: http
              containerPort: {{ .Values.port }}
            {{- with .Values.grpcPort }}
            - name: grpc
              containerPort: {{ . }}
            {{- end }}
          env:
            {{- include "service-lib.env" . | nindent 12 }}
          readinessProbe:
            httpGet: { path: /health/ready, port: http }
            periodSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet: { path: /health/live, port: http }
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
          startupProbe:
            httpGet: { path: /health/live, port: http }
            periodSeconds: 2
            failureThreshold: 60
          # Ждём, пока endpoint уберут из балансировки, затем uvicorn дорабатывает запросы
          lifecycle:
            preStop:
              exec:
                command: ["sleep", "5"]
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          securityContext:
            {{- include "service-lib.containerSecurityContext" . | nindent 12 }}
          volumeMounts:
            {{- include "service-lib.volumeMounts" . | nindent 12 }}
      volumes:
        {{- include "service-lib.volumes" . | nindent 8 }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ include "service-lib.name" . }}
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
spec:
  selector:
    {{- include "service-lib.selector" . | nindent 4 }}
    app.kubernetes.io/component: api
  ports:
    - name: http
      port: {{ .Values.port }}
      targetPort: http
    {{- with .Values.grpcPort }}
    - name: grpc
      port: {{ . }}
      targetPort: grpc
    {{- end }}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "service-lib.name" . }}
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      {{- include "service-lib.selector" . | nindent 6 }}
      app.kubernetes.io/component: api
{{- if .Values.hpa.enabled }}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "service-lib.name" . }}
  labels:
    {{- include "service-lib.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "service-lib.name" . }}
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.hpa.cpuUtilization }}
{{- end }}
{{- end }}
