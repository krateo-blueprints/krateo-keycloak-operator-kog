---
type: Configuration
title: keycloak-config-kog — configuration
description: The whole chart values surface — the Keycloak target, the ESO-minted admin token, which RestDefinitions to emit, and the Snowplow delegation used by KeycloakAuthenticationExecution.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [keycloak, values, eso, snowplow, restdefinitions]
timestamp: 2026-08-11T00:00:00Z
---

# Configuration

Everything is `chart/values.yaml`, typed by `chart/values.schema.json`
(title `Keycloak Config KOG`). The top-level keys are `keycloak`, `auth`,
`restDefinitions`, `snowplow`, `resourceGroup`, `verbose`.

## Keycloak target (`keycloak.*`)

| key | default | effect |
|---|---|---|
| `keycloak.baseUrl` | `http://keycloak-service.keycloak-system.svc.cluster.local:8080` | Base URL of the Keycloak server the generated controllers call (**no trailing slash**). Injected into every OAS asset's `servers[0].url` via Helm `tpl`. The default points at the in-cluster Service created by the operator blueprint. |

## Admin bearer token (`auth.*`)

rest-dynamic-controller reads a bearer token from a Secret referenced by each CR's
`<Kind>Configuration`. Because Keycloak admin tokens are short-lived, the chart does
**not** store a static token: ESO mints a fresh one on a sub-TTL interval.

| key | default | effect |
|---|---|---|
| `auth.secretName` | `keycloak-admin-token` | the Secret ESO writes the token into; every `<Kind>Configuration.spec.authentication.bearer.tokenRef` points here. |
| `auth.secretKey` | `token` | the key within that Secret. |
| `auth.externalSecret.enabled` | `true` | render the ESO `Webhook` generator + `ExternalSecret`. Set `false` to supply the token Secret yourself. |
| `auth.externalSecret.refreshInterval` | `60s` | must stay **below** the Keycloak access-token lifespan so the bearer never goes stale. |
| `auth.externalSecret.generatorRef` | `Webhook` `keycloak-admin-token-webhook` | the ESO Generator (preferred) or SecretStore that yields the token. |
| `auth.externalSecret.tokenEndpoint` | `…/realms/master/protocol/openid-connect/token` | Keycloak's `client_credentials` token endpoint the generator POSTs to. |
| `auth.externalSecret.clientId` | `krateo-kog` | the service-account client that mints the token. Needs `serviceAccountsEnabled` + `realm-management` roles. |
| `auth.externalSecret.clientSecretRef.name` / `.key` | `keycloak-kog-client` / `clientSecret` | a **pre-existing** Secret holding the client secret (never stored in values). The Secret must carry the `external-secrets.io/type: webhook` label or ESO refuses to read it. |

The generated `ExternalSecret` is `external-secrets.io/v1` (v1beta1 is removed); the
Webhook body references the secret as `.kog.clientSecret` (name-then-key), and
`result.jsonPath: "$"` returns the whole token response so the template can pick
`.access_token`.

## Which RestDefinitions to emit (`restDefinitions.*`)

Each entry maps 1:1 to an `assets/<key>.yaml` OAS and, when `enabled: true`, renders a
`RestDefinition` + its OAS `ConfigMap`. `kind` is intentionally prefixed `Keycloak` to
avoid crdgen collisions with same-named lowercase body properties (the Nova KOG's
`Server` vs `server` failure mode).

| key | default kind | enabled |
|---|---|---|
| `realm` | `KeycloakRealm` | `true` |
| `client` | `KeycloakClient` | `true` |
| `protocolmapper` | `KeycloakProtocolMapper` | `true` |
| `clientscope` | `KeycloakClientScope` | `true` |
| `group` | `KeycloakGroup` | `true` |
| `user` | `KeycloakUser` | `true` |
| `identityprovider` | `KeycloakIdentityProvider` | `true` |
| `idpmapper` | `KeycloakIdentityProviderMapper` | `true` |
| `authenticationflow` | `KeycloakAuthenticationFlow` | `true` |
| `requiredaction` | `KeycloakRequiredAction` | `true` |
| `authenticationexecution` | `KeycloakAuthenticationExecution` | `true` |

`KeycloakUser` requires rest-dynamic-controller ≥ 0.16.1 and oasgen-provider ≥ 0.14.1
(0.16.0 is the true floor for the `[?key=value]` credential matching, but 0.16.0
cannot delete a CR whose create failed, so 0.16.1 is the stated floor). Disable any
resource you do not need by setting `restDefinitions.<key>.enabled: false`.

## Snowplow delegation (`snowplow.*`)

Used by `restDefinitions.authenticationexecution` **only**. Keycloak's executions API
is create-then-mutate, so that resource delegates its lifecycle verbs to Snowplow
`RESTAction`s.

| key | default | effect |
|---|---|---|
| `snowplow.endpointSecretName` | `keycloak-admin-endpoint` | the Snowplow Endpoint-shaped Secret (keys: `server-url`, `token`) the `KeycloakAuthenticationExecution` RESTActions call Keycloak through. Rendered in the release namespace by `templates/externalsecret.yaml` (same rotated admin token as `auth.secretName`). If `auth.externalSecret.enabled` is `false`, supply this Secret yourself. |

This surface additionally requires Snowplow + authn wired into the rdc deployment
(`URL_SNOWPLOW`/`URL_AUTHN` + a projected authn token) — the stock oasgen rdc
templates do **not** set these.

## Group and logging (`resourceGroup`, `verbose`)

| key | default | effect |
|---|---|---|
| `resourceGroup` | `keycloak.ogen.krateo.io` | the Kubernetes API group the generated CRDs register under. GVK = `<resourceGroup>/v1alpha1`. |
| `verbose` | `false` | verbose logging on the generated connectors (the `krateo.io/connector-verbose` annotation on each `RestDefinition`). |
