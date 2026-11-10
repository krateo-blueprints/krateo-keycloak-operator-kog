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
`restDefinitions`, `snowplow`, `resourceGroup`.

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
| `auth.externalSecret.refreshInterval` | `30s` | must stay **well below** the Keycloak access-token lifespan so the bearer never goes stale. The master realm defaults to 60 s (measured `exp - iat = 60`), so 30 s leaves half a lifetime of margin. |
| `auth.externalSecret.generatorRef` | `Webhook` `keycloak-admin-token-webhook` | the ESO Generator (preferred) or SecretStore that yields the token. |
| `auth.externalSecret.tokenEndpoint` | `…/realms/master/protocol/openid-connect/token` | Keycloak's `client_credentials` token endpoint the generator POSTs to. |
| `auth.externalSecret.clientId` | `krateo-kog` | the service-account client that mints the token. Needs `serviceAccountsEnabled` + `realm-management` roles. |
| `auth.externalSecret.clientSecretRef.name` / `.key` | `keycloak-kog-client` / `clientSecret` | a **pre-existing** Secret holding the client secret (never stored in values). The Secret must carry the `external-secrets.io/type: webhook` label or ESO refuses to read it. |

### Authenticating as the blueprint's bootstrap service account (`auth.bootstrap.*`)

| key | default | effect |
|---|---|---|
| `auth.bootstrap.enabled` | `false` | authenticate as the bootstrap admin service account that krateo-keycloak-blueprint (>= 0.2.3) creates, instead of `auth.externalSecret.clientId` / `clientSecretRef`. A fresh install then needs **no hand-made client**. |
| `auth.bootstrap.namespace` | `""` | namespace of the blueprint's Keycloak (where its bootstrap Secret lives). **Required** when enabled. |
| `auth.bootstrap.secretName` | `keycloak-bootstrap-service` | the blueprint's bootstrap service-account Secret (keys `client-id`, `client-secret`). |

ESO generators only read Secrets in their own namespace, so the chart copies that ONE Secret
into the release namespace: an ESO Kubernetes `SecretStore` whose ServiceAccount has a Role in
the Keycloak namespace granting `get` on exactly that Secret (by `resourceNames`), plus an
`ExternalSecret` that writes the copy with the `external-secrets.io/type=webhook` label the
generator requires. Verified live against blueprint 0.2.3 + its operator: the copy matches the
source, the reader can get nothing else (not the bootstrap user's Secret, not the DB Secret, no
`list`), and the minted token (`azp=krateo-bootstrap`) reads (200) and writes (201) the admin API.

The bootstrap service account is **temporary** by Keycloak's definition. In the planned end
state, the KOG uses it to create its permanent `krateo-kog` client, switches to it, and deletes
the bootstrap accounts. That step is not shipped yet.

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

`KeycloakUser` requires oasgen-provider **>= 0.56.0** (the release ships
rest-dynamic-controller at the same version). 0.56.0 is the first release that both
provisions the per-namespace Role granting the controller read access to each user's
Secrets (krateo-platformops/oasgen-provider#510), and honours the per-credential guard that
makes a password-only (or OTP-only) user valid (krateo-platformops/oasgen-provider#524, #20).
On 0.53.0 – 0.55.x no `KeycloakUser` reconciles at all; on 0.20.0 – 0.52.0 only users
carrying both a password and an OTP credential do.

Upgrade the **`oasgen-provider-crds`** chart to the same version as the provider. The
RestDefinition CRD carries the new status fields (`secretRefDigest`, `secretRefRBACNamespaces`)
and `resolver.when`. If the provider moves without its CRD chart, the API server prunes those
fields: the guard disappears, and the provider re-runs Update on every pass while revocation
silently does nothing.

**Secret access follows users on the provider's poll, not instantly.** The Role granting
the controller read access to a user's Secrets is created and trimmed on oasgen-provider's
drift poll (3 minutes by default). After you delete a `KeycloakUser`, its Secrets stay
readable by the controller until the next poll; we measured 61–101 s on kind. Nothing
watches the generated kind yet (krateo-platformops/oasgen-provider#510).

**Password-only users need the #524 guard, and an older controller drops it silently.** Each
credential mapping in `rd-user.yaml` carries `resolver.when.customResourceFieldPresent`. On an
oasgen-provider without #524, the RestDefinition CRD's `resolver` schema has no such field and no
`x-kubernetes-preserve-unknown-fields`, so the API server **prunes `when` at apply time without an
error**: the chart installs cleanly, and every password-only `KeycloakUser` then fails as in #20. To
check that the guard survived, read it back from the live object rather than trusting a successful
apply:

```bash
kubectl -n <ns> get restdefinition <release>-user \
  -o jsonpath='{.spec.resource.verbsDescription[*].fieldMapping[*].resolver.when}'
```

An empty result means the controller is too old for this chart.

**`KeycloakUser` Secret format** (measured against Keycloak 26.4):

- the password key holds the plain password;
- the OTP key holds Keycloak's JSON form `{"value":"<shared secret>"}`, not a bare seed
  (a bare seed fails the create with HTTP 500, `JsonParseException`). The `value` string is
  itself the TOTP key; an authenticator app needs its Base32 encoding;
- `spec.username` must be at least 3 characters (Keycloak's default user profile;
  shorter is refused with `error-invalid-length`, HTTP 400).
- **OTP is enrolled once, at create.** Updates keep sending the password (so it rotates) but
  never the OTP credential: Keycloak refuses to recreate an existing OTP (HTTP 409, reported as
  "User exists with same username or email"), which used to make every spec update of an OTP
  user fail. To change an OTP seed, recreate the `KeycloakUser`.
- **Rotating a password:** update the Secret, then change the `KeycloakUser` spec (any field).
  A Secret change alone doesn't trigger a reconcile.

Disable any
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

## Execution identity (`executionIdentity.*`)

`KeycloakAuthenticationExecution` delegates its lifecycle to Snowplow `RESTAction`s, and its
controller authenticates to snowplow through authn. When `restDefinitions.authenticationexecution`
is enabled, the chart renders what that needs, so nothing is applied by hand:

| key | default | effect |
|---|---|---|
| `executionIdentity.enabled` | `true` | render the objects below. Requires the authn CRDs (`serviceaccount.authn.krateo.io`). |
| `executionIdentity.group` | `krateo:rdc` | authn group the controller's identity joins. |
| `executionIdentity.snowplowServiceAccount.name` / `.namespace` | `snowplow` / release namespace | snowplow's ServiceAccount. |

- an authn `ServiceAccount` allowlist CR for the execution controller, named the way oasgen names
  its ServiceAccount (`<lowercase kind>s-<resourceGroup>-v1alpha1`);
- a Role granting `get` on **only** this chart's four RESTActions, bound to that group;
- a Role letting snowplow `get` **only** the Endpoint Secret (`snowplow.endpointSecretName`).

Verified live: with these objects removed, the execution controller is refused by authn (`403 no
ServiceAccount mapping … not in the exchange allowlist`); with the chart rendering them, every
execution reconciles. The controllers still need the RDC wiring (`URL_SNOWPLOW`, `URL_AUTHN`, the
projected authn token), which are oasgen-provider chart values (see ARCHITECTURE).

## Group (`resourceGroup`)

| key | default | effect |
|---|---|---|
| `resourceGroup` | `keycloak.ogen.krateo.io` | the Kubernetes API group the generated CRDs register under. Resource kinds are `<resourceGroup>/v1` (each OAS asset's `info.version`); their `<Kind>Configuration` companions are `<resourceGroup>/v1alpha1`. |

## Debugging a resource (per-resource verbose)

Verbosity is set **per custom resource**, not by this chart. The generated controller reads
`krateo.io/connector-verbose` from the resource it is reconciling and from nothing else, so
annotate the one resource you are debugging:

```yaml
apiVersion: keycloak.ogen.krateo.io/v1
kind: KeycloakUser
metadata:
  name: alice
  annotations:
    krateo.io/connector-verbose: "true"   # dumps this resource's HTTP exchanges to the controller log
spec:
  # ...
```

or on a live resource:

```bash
kubectl annotate keycloakuser alice krateo.io/connector-verbose=true      # on
kubectl annotate keycloakuser alice krateo.io/connector-verbose-          # off
```

Each request and response is then written to the log of that kind's controller
(`<release>-<kind>-controller` in the release namespace), headers and body included.
On the supported controller floor (oasgen-provider >= 0.56.0), **requests** are redacted: the
`Authorization` header and every secretRef-resolved value (passwords, OTP seeds, client
secrets) are written as `***REDACTED***`.

**Responses are NOT redacted: they are dumped verbatim, headers included, whether or not pretty
JSON is on** (oasgen-provider#566). Keycloak's admin API returns some
secrets in its responses. Measured on 0.56.0: with verbose on a `KeycloakClient`, the findby
response (`GET …/clients`, the realm's whole client list) wrote the client secret of every
confidential client in the realm into the controller log. **Never enable verbose on
`KeycloakClient`** in a cluster whose logs anyone else can read, and treat any log captured
with it as containing those secrets. Remember that controller logs are usually shipped to a
central store, read by more people than can run `kubectl logs`. `KeycloakUser` and `KeycloakIdentityProvider` responses
were checked and do not carry their secrets: Keycloak never returns passwords and masks an
IdP's clientSecret as `**********`.

Below oasgen-provider 0.26.1 even the request bearer token was dumped in cleartext, so do not
enable it on an older install. Turn it off when you are done: the dump is per request and noisy.

Before 0.4.7 this chart had a `verbose` value that put the annotation on each
`RestDefinition`. Nothing reads it there, so it never had any effect, and it was removed
in 0.4.7. A values file that still sets `verbose` installs unchanged and the key is ignored.
