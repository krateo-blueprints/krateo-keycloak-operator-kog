---
type: Architecture
title: keycloak-config-kog — overview
description: What the blueprint does and how it is built — one RestDefinition per Keycloak resource over a curated OAS subset, the patched bearer securityScheme, the ESO-minted short-lived admin token, findby UUID addressing, and the Snowplow-delegated authentication-execution surface.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [keycloak, kog, oasgen-provider, rest-dynamic-controller, eso]
timestamp: 2026-08-11T00:00:00Z
---

# Overview

keycloak-config-kog is Keycloak-as-code for Krateo. It packages a set of
`RestDefinition`s (one per Keycloak Admin API resource) so that the KOG toolchain —
[`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider) generating
CRDs and [`rest-dynamic-controller`](https://github.com/krateo-platformops/rest-dynamic-controller)
reconciling them — turns each resource into a native Kubernetes custom resource. A
`KeycloakClient` CR becomes a real client in Keycloak; a `KeycloakRealm` CR becomes a
real realm. No plugin, no operator code for the CRUD path — the controllers drive
Keycloak's own Admin REST API.

This is the **configuration** deliverable. The **lifecycle** deliverable (standing
Keycloak up) is the sibling
[`krateo-keycloak-blueprint`](https://github.com/krateo-blueprints/krateo-keycloak-blueprint),
which wraps the official Keycloak Operator. They connect at exactly one point: the
bearer `keycloak-admin-token` Secret that this KOG uses to call the server the
blueprint stands up. The full design is in [ARCHITECTURE.md](./ARCHITECTURE.md).

## What the chart deploys

`helm install` renders, for every enabled resource in `restDefinitions`
([configuration](./configuration.md)):

| manifest | kind | role |
|---|---|---|
| `rd-<key>.yaml` | `RestDefinition` (ogen.krateo.io/v1alpha1) | the KOG spec: which Keycloak verbs/paths map to CR create/findby/get/update/delete |
| `configmaps.yaml` | `ConfigMap` | the curated OAS subset for that resource (`assets/<key>.yaml`), with `servers[0].url` templated from `keycloak.baseUrl` |
| `externalsecret.yaml` | `Webhook` generator + `ExternalSecret` | ESO minting/rotating the short-lived admin bearer token into the `keycloak-admin-token` Secret |
| `restactions-authenticationexecution.yaml` | four Snowplow `RESTAction`s | the delegated observe/create/update/delete for `KeycloakAuthenticationExecution` |

Each `RestDefinition` maps 1:1 to a hand-curated OAS subset in
`chart/assets/<key>.yaml`. The curated schemas use field names verbatim from
Keycloak's official OAS 3.0.3 so request bodies stay wire-compatible, but they trim
the huge `*Representation` schemas (`RealmRepresentation` alone is 152 fields) down to
the SSO-relevant subset.

## Resources exposed

Every generated kind lives under `keycloak.ogen.krateo.io/v1alpha1`
(`resourceGroup`):

| CR Kind | Keycloak resource | Addressing |
|---|---|---|
| `KeycloakRealm` | realm | natural key `realm` (direct); also carries OTP/WebAuthn policy + top-level flow bindings |
| `KeycloakClient` | client | `clientId` → UUID via `findby`; supports inline `protocolMappers` |
| `KeycloakProtocolMapper` | protocol mapper on a client-scope / pre-existing client | `name` → UUID via `findby`; parent `clientUuid` |
| `KeycloakClientScope` | client scope | `name` → UUID via `findby` |
| `KeycloakGroup` | group | `name` → UUID via `findby` |
| `KeycloakUser` | realm user (credentials sourced from a Secret) | `username` → UUID via `findby` |
| `KeycloakIdentityProvider` | IdP instance (e.g. GitHub broker) | natural key `alias` (direct) |
| `KeycloakIdentityProviderMapper` | mapper on an IdP instance | `name` → UUID via `findby`; parent `alias` |
| `KeycloakAuthenticationFlow` | authentication flow (top-level container) | `alias` → UUID via `findby` |
| `KeycloakRequiredAction` | required-action provider (`CONFIGURE_TOTP`, `webauthn-register`, …) | natural key `alias` (direct) |
| `KeycloakAuthenticationExecution` | one execution/subflow **inside** a flow | `(realm, flowAlias, provider \| alias)` via delegated Snowplow `RESTAction`s |

For **UUID-addressed** resources (client/group/client-scope/mapper/user) `findby`
lists the collection and matches the natural key (`clientId`/`name`/`username`) to
resolve the server-generated `id`, which lands in `status.id` and feeds
get/update/delete via `requestFieldMapping`. **Direct** resources (realm,
identity-provider, required-action, flow) use their natural key straight in the path.

## Two design decisions baked in

1. **`securitySchemes` patched into every OAS asset.** Keycloak's published OAS omits
   a security scheme; KOG only accepts `http/basic` or `http/bearer`. Every asset
   declares `bearer` (`http`/`bearer`) and applies it globally, so oasgen-provider
   generates the paired `<Kind>Configuration` CRD that carries the auth block. No auth
   bridge is needed — the Admin API is genuinely Bearer (unlike the Nova KOG, which
   had to rewrite `X-Auth-Token`).

2. **Short-lived admin token via External Secrets Operator.** Keycloak admin access
   tokens live only minutes. Rather than a static Secret, `templates/externalsecret.yaml`
   has an ESO `Webhook` generator mint a fresh token from Keycloak's token endpoint
   (`client_credentials`, a service-account client holding `realm-management` roles) on
   a `refreshInterval` shorter than the token TTL, writing it into the
   `keycloak-admin-token` Secret that every `<Kind>Configuration` references.

## Corrections the design bakes in

Three constraints the initial spike surfaced (now applied to all RDs):

1. **Path params must be declared at the OPERATION level** in the OAS asset —
   oasgen-provider ignores path-item-level `parameters`, so the param (e.g. `realm`)
   would never land in the generated CRD.
2. **Server-generated id must be excluded from spec.** The `{id}` path param is added
   to the CRD as *required*; since it is server-assigned, each RD uses
   `excludedSpecFields: [id]` + `requestFieldMapping` sourcing it from `status.id`
   (populated by `findby`).
3. **Nested array fields need a `$ref`.** oasgen-provider drops inline array-of-object
   items, so `protocolMappers` references a named `ClientProtocolMapperEntry` schema
   instead of an inline object.

## The authentication-execution surface is delegated

Executions **inside** a flow are not a plain `RestDefinition`. Keycloak's
`authentication/executions` API is create-then-mutate — an execution is created at
`.../executions/execution` (its `priority` ordering weight is honored at create but
**immutable** afterwards), and its `requirement` is a separate flow-scoped PUT. So
`KeycloakAuthenticationExecution` **delegates observe/create/update/delete to Snowplow
`RESTAction`s** (`observeApiRef`/`createApiRef`/`updateApiRef`/`deleteApiRef`) — full
reconcile, no plugin, no operator code. Ordering is **declarative**: `spec.priority`
is Keycloak's native ascending weight (use spaced values, 10/20/30), sent at create;
priority drift converges by delete + re-create. This surface requires Snowplow + authn
wired into the rdc deployment (`URL_SNOWPLOW`/`URL_AUTHN`). See
[ARCHITECTURE.md](./ARCHITECTURE.md#authentication-flows--executions-mfa--acr) and
[configuration](./configuration.md).

## Authentication & MFA

`KeycloakRealm` also carries the realm **OTP** (`otpPolicy*`) and **WebAuthn**
(`webAuthnPolicy*`, incl. passwordless) policy fields plus the top-level flow bindings
(`browserFlow`, `directGrantFlow`); `KeycloakRequiredAction` toggles the built-in MFA
actions; `KeycloakAuthenticationFlow` manages a top-level flow container.
**ACR → Level-of-Authentication** mapping is the standard `acr.loa.map` client
attribute (set `default.acr.values` for the default level) — expressed directly on
`KeycloakClient.attributes`, so issued tokens carry the `acr` claim per level. The
sample `samples/20-authentication-mfa.yaml` assembles the canonical step-up ladder
(LoA 1 = password, LoA 2 = OTP).
