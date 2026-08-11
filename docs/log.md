---
type: Log
title: keycloak-config-kog — log
description: Curated chronological history of keycloak-config-kog — notable changes, validation milestones and design decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [log, history, keycloak]
timestamp: 2026-08-11T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.

## 2026-08-11 — Documentation Standard adoption

The repo adopts the Krateo Documentation Standard (OKF): the invariant docs bundle
(`docs/{index,overview,usage,configuration,api,examples,release,log}.md` + `llms.txt`),
a runnable `examples/sso-realm`, and the shared `lint-docs` check wired into a new
`lint.yaml`. The pre-existing `docs/ARCHITECTURE.md` and `docs/images/README.md` gain
OKF frontmatter (type `Architecture`). `README.md` is restructured into the six
standard sections.

## 2026-07-21 — KeycloakAuthenticationExecution proven in-cluster

The full step-up ladder reconciled on a kind cluster with published images only
(oasgen-provider 0.12.0 / rdc 0.11.0 / snowplow 1.7.13 cache-off / authn 0.24.0):
`kubectl apply` of the 9-CR sample converged the complete LoA ladder into a live
Keycloak 26 — exact order by declarative priority, requirements, both LoA configs —
and `kubectl delete` held the finalizer until the single-execution GET returned a real
404. Mid-run Keycloak restarted and wiped its dev database; the controllers rebuilt the
whole ladder from the CRs unattended. `KeycloakAuthenticationFlow` and `KeycloakRealm`
also reconciled Ready=True in the same e2e.

## Earlier — the seven core resources validated

`KeycloakRealm`, `KeycloakGroup`, `KeycloakClientScope`, `KeycloakClient`,
`KeycloakProtocolMapper`, `KeycloakIdentityProvider` and
`KeycloakIdentityProviderMapper` each reconciled into a real Keycloak 26.6.3 on a live
kind cluster (`oasgen-provider` 0.10 + rest-dynamic-controller). Findings baked into
the design:

- Path params must be declared at the **operation** level in the OAS asset
  (oasgen-provider ignores path-item-level parameters).
- The server-generated `{id}` must be excluded from spec and sourced from `status.id`
  via `requestFieldMapping`.
- Nested array fields (`protocolMappers`) need a named `$ref`, not an inline object.
- `KeycloakIdentityProviderMapper` needs both `alias` (path) **and**
  `identityProviderAlias` (body) — omitting the latter yields a misleading
  `409 Duplicate resource`.
- The ESO admin-token path works end-to-end on ESO ≥ 0.19: the client-secret Secret
  must carry the `external-secrets.io/type: webhook` label, the `krateo-kog` client
  needs `serviceAccountsEnabled` + admin rights, the `ExternalSecret` is
  `external-secrets.io/v1`, and `result.jsonPath: "$"` returns the whole token
  response so the template can pick `.access_token`.

## Design origin

Two deliverables bring Keycloak into the platform: this **configuration** KOG and the
sibling **lifecycle** blueprint that wraps the official Keycloak Operator. The
operator-for-lifecycle / KOG-for-config split avoids two systems owning the same
realm; the Bitnami chart was intentionally avoided (deprecated Aug 2025). Every OAS
asset patches in a `bearer` `securityScheme` (Keycloak's published OAS omits one), so
no auth-bridge proxy is required.
