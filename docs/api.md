---
type: API
title: keycloak-config-kog — API
description: The CompositionDefinition CRD this blueprint registers, the KeycloakConfigKog Composition kind it derives, and the generated Keycloak resource kinds (realm/client/mapper/group/IdP/flow/execution) the RestDefinitions produce.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [keycloak, compositiondefinition, crd, restdefinition, api]
timestamp: 2026-08-11T00:00:00Z
---

# API

This blueprint exposes two API layers: the Krateo `CompositionDefinition` that
registers the chart, and the Keycloak resource CRDs the chart's `RestDefinition`s
generate.

## The CompositionDefinition CRD

`compositiondefinition.yaml` is this blueprint's own registration. It is a
`CompositionDefinition` (`core.krateo.io/v1alpha1`) — the Krateo core-provider CRD that
tells Krateo to fetch a chart, generate a typed CRD from its `values.schema.json`, and
reconcile Composition instances against it.

```yaml
apiVersion: core.krateo.io/v1alpha1
kind: CompositionDefinition
metadata:
  name: keycloak-config-kog
  namespace: krateo-system
spec:
  chart:
    url: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
    version: "0.1.0"
```

| field | type | meaning |
|---|---|---|
| `spec.chart.url` | string | OCI reference of the published chart. `release-chart.yaml` pushes to `oci://ghcr.io/<owner>/charts/keycloak-config-kog`. |
| `spec.chart.version` | string | the published chart version this definition installs. Bump it to the released chart version on `main` after publishing. |

Applying this `CompositionDefinition` makes core-provider derive, from the chart's
`Chart.yaml` and `values.schema.json`, a **Composition CRD**:

- **Kind** from the chart `name` (`keycloak-config-kog`), dashes dropped and
  CamelCased → `KeycloakConfigKog`.
- **apiVersion** from the chart `version` → `composition.krateo.io/v<major>-<minor>-<patch>`
  (e.g. version `0.1.0` → `composition.krateo.io/v0-1-0`).

A Composition instance is then a CR of that Kind whose `spec` mirrors the chart
`values` (typed by `values.schema.json`). The runnable instance is
`examples/composition.yaml` ([examples](./examples.md)); the full value surface is in
[configuration](./configuration.md).

## The generated Keycloak resource kinds

Installing the chart registers one `RestDefinition` (`ogen.krateo.io/v1alpha1`) per
enabled resource; oasgen-provider turns each into a pair of CRDs under
`keycloak.ogen.krateo.io/v1alpha1` (the `resourceGroup`):

- a **resource CRD** (e.g. `KeycloakClient`) — the Keycloak resource itself, and
- a **`<Kind>Configuration` CRD** (e.g. `KeycloakClientConfiguration`) — carrying the
  `spec.authentication.bearer.tokenRef` that points every CR at the ESO-managed
  `keycloak-admin-token` Secret (`samples/00-configurations.yaml`).

Each resource CR references its Configuration via `spec.configurationRef`.

| CR Kind | Keycloak verbs (from `verbsDescription`) | Addressing |
|---|---|---|
| `KeycloakRealm` | create `POST /admin/realms`; get/update/delete `…/realms/{realm}`; findby `GET /admin/realms` | natural key `realm`; `id` read-only in `status` |
| `KeycloakClient` | findby `…/clients`; create `POST …/clients`; get/update/delete `…/clients/{id}` | `clientId` → `id` via findby; inline `protocolMappers` supported |
| `KeycloakProtocolMapper` | findby + CRUD on `…/client-scopes` or client mappers | `name` → UUID via findby; parent `clientUuid` |
| `KeycloakClientScope` | findby + CRUD on `…/client-scopes/{id}` | `name` → UUID via findby |
| `KeycloakGroup` | findby + CRUD on `…/groups/{id}` | `name` → UUID via findby |
| `KeycloakUser` | findby + CRUD on `…/users/{id}`; credentials from a Secret | `username` → UUID via findby |
| `KeycloakIdentityProvider` | CRUD on `…/identity-provider/instances/{alias}` | natural key `alias` |
| `KeycloakIdentityProviderMapper` | findby + CRUD on IdP mappers | `name` → UUID via findby; needs both `alias` (path) **and** `identityProviderAlias` (body) |
| `KeycloakAuthenticationFlow` | findby + CRUD on `…/authentication/flows` | `alias` → UUID via findby |
| `KeycloakRequiredAction` | CRUD on `…/authentication/required-actions/{alias}` | natural key `alias`; base actions ship built-in (reconcile observes+updates) |
| `KeycloakAuthenticationExecution` | delegated — see below | `(realm, flowAlias, provider \| alias)` |

For UUID-addressed kinds the RD declares `excludedSpecFields: [id]` and sources `{id}`
from `status.id` (populated by findby) via `requestFieldMapping`; `{realm}` stays a
normal required spec field.

## KeycloakAuthenticationExecution — the delegated contract

`KeycloakAuthenticationExecution` is not a plain `RestDefinition`. Keycloak's
`authentication/executions` API is create-then-mutate (`priority` honored at create,
immutable afterwards; `requirement` via a flow-scoped PUT), so the four lifecycle verbs
are **delegated to Snowplow `RESTAction`s** through `observeApiRef` / `createApiRef` /
`updateApiRef` / `deleteApiRef` (`chart/templates/rd-authenticationexecution.yaml` +
`restactions-authenticationexecution.yaml`).

- **Identifiers:** `realm`, `flowAlias`, `provider`, `alias`, `subFlow`.
- **Status fields:** `id`, `requirement`, `index`, `level`, `priority`, `found`,
  `configured`.
- **observe** — lists the parent flow's executions, selects this one (level 0 +
  provider / subflow alias), composes
  `{found, id, requirement, index, level, priority, configured}`.
  `notFoundExpr` (`(.status.found // false) | not`) gates the non-idempotent create;
  `upToDateExpr` detects requirement / priority / config drift.
- **create** — `POST …/executions/execution`, fired only while the execution is
  missing.
- **update** — requirement mismatch, priority mismatch (immutable weight ⇒ recreate),
  or a declared-but-missing authenticator config.
- **delete** — plus a finalizer-verified `GET …/executions/{executionId}` that must
  404 before the finalizer is released.

Ordering is declarative: `spec.priority` is Keycloak's native ascending weight (use
spaced values, 10/20/30). The full delegation model is in
[ARCHITECTURE.md](./ARCHITECTURE.md#authentication-flows--executions-mfa--acr), and the
offline tests that assert the extracted jq are in `tests/delegation/`.

## Authentication & ACR fields

- `KeycloakRealm` carries OTP (`otpPolicy*`) and WebAuthn (`webAuthnPolicy*`) policy
  fields and top-level flow bindings (`browserFlow`, `directGrantFlow`).
- `KeycloakRequiredAction` toggles the built-in MFA actions (`CONFIGURE_TOTP`,
  `webauthn-register`).
- **ACR → LoA** is the standard `acr.loa.map` client attribute on
  `KeycloakClient.attributes` (set `default.acr.values` for the default level), so
  issued tokens carry the `acr` claim per level. See `samples/20-authentication-mfa.yaml`.
