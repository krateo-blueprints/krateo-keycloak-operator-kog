---
type: ExampleIndex
title: keycloak-config-kog — examples
description: Index of the runnable examples under examples/ — the SSO-realm CR walkthrough and the single-Composition install manifest.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [examples, keycloak, sso]
timestamp: 2026-08-11T00:00:00Z
---

# Examples

- [examples/sso-realm](../examples/sso-realm/README.md) — an end-to-end SSO realm
  expressed entirely as keycloak-config-kog custom resources: a `krateo` realm, the
  `keystone` and `krateo-authn` OIDC clients, an inline `groups` mapper, and an
  OpenStack project group. Uses the repo-root samples
  (`samples/00-configurations.yaml`, `samples/10-sso-realm.yaml`) so it stays in sync
  with the validated walkthrough.
- [examples/composition.yaml](../examples/composition.yaml) — the Krateo Composition
  form of the install: one `KeycloakConfigKog` CR that installs the RestDefinitions +
  ESO token wiring, instead of a `helm install`. Per-resource CRs are applied
  separately once the CRDs exist.

Ready-to-edit resource manifests live at the repo root under `samples/`
(`00-configurations.yaml`, `10-sso-realm.yaml`, `20-authentication-mfa.yaml`), and
longer end-to-end walkthroughs (GitHub SSO, MFA step-up, Horizon SSO) live under
`demo/`.
