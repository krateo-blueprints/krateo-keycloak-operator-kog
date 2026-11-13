{{- define "keycloak-config-kog.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* configmap name holding the OAS for a given resource key */}}
{{- define "keycloak-config-kog.cmName" -}}
{{- printf "%s-%s" .root.Release.Name .key -}}
{{- end -}}

{{- /*
The effective restDefinitions: this chart's own values.yaml defaults, with the supplied values merged
over them. `helm upgrade --reuse-values` upgrades with the PREVIOUS release's values and does not apply
the new chart's defaults, so a key added since (e.g. userprofile in 0.7.0) would be missing and a
template reading it would fail with a nil pointer. Helm does not expose values.yaml through .Files,
so the defaults live in files/restDefinitions.defaults.yaml (CI keeps it equal to values.yaml's).
Every template reads restDefinitions through this helper.
*/ -}}
{{- define "keycloak-config-kog.restDefinitions" -}}
{{- $defaults := .Files.Get "files/restDefinitions.defaults.yaml" | fromYaml | default dict -}}
{{- toYaml (mergeOverwrite (deepCopy $defaults) (.Values.restDefinitions | default dict)) -}}
{{- end -}}

{{- /* The client_credentials token endpoint: auth.externalSecret.tokenEndpoint when set, otherwise derived
from keycloak.baseUrl, so the token is minted by the same Keycloak the controllers call (a path prefix
in baseUrl, e.g. /keycloak, is carried over). */ -}}
{{- define "keycloak-config-kog.tokenEndpoint" -}}
{{- $te := (.Values.auth.externalSecret).tokenEndpoint | default "" -}}
{{- if $te -}}
{{- $te -}}
{{- else -}}
{{- printf "%s/realms/master/protocol/openid-connect/token" (.Values.keycloak.baseUrl | trimSuffix "/") -}}
{{- end -}}
{{- end -}}
