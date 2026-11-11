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

## 2026-11-11 — 0.6.0: realm mail (password and XOAUTH2), events and action-link lifetimes

`KeycloakRealm` gains `smtpServer` (password or token authentication), the user-event settings, the
action-token lifespans and `verifyEmail`, for an access-request flow where an administrator approves a
request and Keycloak emails the new user a set-password link. SMTP credentials are Secret-sourced
(`smtpCredentialsRef`: the user, and the password or the OAuth2 client secret) and never stored in the
CR. Validated live on disposable GKE clusters against the shipped stack (keycloak-operator 0.2.4,
keycloak 0.2.5 on CloudNativePG, Keycloak 26.6.3) on rest-dynamic-controller 0.56.0 and 0.59.0, with
Keycloak admin events as the oracle for every write: a real set-password email delivered through
SMTP AUTH (password) and through `AUTH XOAUTH2` (token, against a stub that accepts only the token it
issued); the masked secret is never compared and an idle realm is never re-PUT; a masked value echoed
back never overwrites the stored one; wrong credentials fail the send with HTTP 500. Two findings went
into the docs and upstream: Keycloak stores no `SEND_EXECUTE_ACTIONS`/`SEND_ERROR` events for an
admin-triggered email, and an in-place change of a referenced Secret never reaches the vendor
(rotate by repointing to a new Secret; oasgen-provider#598).

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
