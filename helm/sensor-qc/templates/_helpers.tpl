{{- define "sensor-qc.name" -}}
{{- printf "%s-sensor-qc" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "sensor-qc.labels" -}}
app.kubernetes.io/name: sensor-qc
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
{{- end -}}
