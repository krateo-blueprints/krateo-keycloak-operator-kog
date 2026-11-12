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

## 2026-11-12 — 0.7.2: restDefinitions.user is declared in the schema

`values.schema.json` never declared `restDefinitions.user` (missing from 0.6.0 to 0.7.1) although
`values.yaml` sets it, so the key could not be set through a Krateo Composition or an installer that
mirrors the schema: it was pruned silently and the default always applied. It is declared now, and CI
gate `hack/check-values-declared.py` requires every `values.yaml` key to be declared. No asset,
template or default changed: a schema widening only. Found by the installer session.

## 2026-11-12 — 0.7.1: the realm's event types and listeners are sets

`enabledEventTypes` and `eventsListeners` declare `uniqueItems: true` (the CRD gets
`x-kubernetes-list-type: set`). With oasgen-provider 0.62.0, which compares such arrays as sets, the
order Keycloak returns them in is no longer drift. Requires oasgen-provider >= 0.62.0 (Chart.yaml
annotation `krateo.io/requires-oasgen-provider`). Descriptions and docs no longer name
`SEND_EXECUTE_ACTIONS`/`SEND_ERROR`, which are not Keycloak EventTypes.

Measured on GKE (Keycloak 26.6.3), one realm with 23 event types, before and after on the same cluster:
oasgen-provider 0.61.0 PUT it at 15:16:30, 15:19:30, 15:22:30 and 15:25:30Z and then stopped ("Drift is
not converging"), leaving it `Ready=False`; 0.62.0 issued no PUT over 15 minutes, observing it up to
date every 3 minutes, `Ready=True`. Positive control: removing `LOGIN` from the live realm produced
exactly one restoring PUT, then up to date again.

## 2026-11-12 — 0.7.0: KeycloakUserProfile

New kind `KeycloakUserProfile`: a realm's declarative user profile (attributes, who may view and
edit them, validators). Keycloak keeps one profile per realm and it always exists, so the kind has
no create and no delete verb: it adopts the realm's profile and replaces it whole (PUT) when it
differs, and deleting the CR leaves the profile in place. The schema is typed (the built-in
validators are modelled), so the generated CRD validates it. See [usage](usage.md).

Measured on a disposable GKE cluster against the shipped stack (Keycloak 26.6.3, keycloak-operator
and keycloak 0.2.6, oasgen-provider 0.60.0), with krateo-keycloak-realm rendering the CR:

- Before the profile existed (realm chart 0.2.0), an attribute set at user creation was dropped.
- After it: the profile was applied with one PUT. The live profile equals the CR except
  `multivalued: false`, Keycloak's default, which is not treated as drift: no further PUT over the
  following minutes, only periodic up-to-date observations.
- Users created before the profile existed (one with only a username, one with every field) both
  accepted admin updates afterwards (204).
- An attribute with view/edit `[admin]`: kept on create, found by `?q=<name>:<value>`, a 37-character
  value refused by `length.max: 36` (400). The user does not see it in the account API, and the
  account API refuses the user's attempt to set it (400 `error-user-attribute-read-only`) while a
  normal profile change by the same user succeeds (204).
- An out-of-band profile edit removing the attribute was reverted by the controller after 63 s. A
  user's stored value survived the window in which the attribute was undeclared.
- Removing the CR (the realm chart with `userProfile.enabled: false`, orphan policy) left the realm's
  profile unchanged; re-enabling adopted it again.

The first reconcile can log one `Cannot observe` (the token Secret is forbidden) when the CR and its
Configuration are created in the same apply: the RBAC that the Configuration grants arrives a moment
later, and the next reconcile succeeds (1.4 s in the run above).

Also: `hack/gen_oas_assets.py` is removed. It no longer reproduced four of the shipped assets, so
running it would have reverted released fixes; the assets are hand-curated and are the source of
truth. README and docs/release.md now describe the current CI and release workflow.

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
