---
type: Component
title: keycloak-config-kog — index
description: The map of the keycloak-config-kog doc bundle — a Krateo Operator Generator (KOG) blueprint that exposes Keycloak Admin API resources (realm, client, mapper, group, IdP, auth flow/execution) as native Kubernetes custom resources.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [keycloak, kog, identity, sso, blueprint]
timestamp: 2026-08-11T00:00:00Z
---

# keycloak-config-kog

keycloak-config-kog is a **Krateo Operator Generator (KOG)** blueprint that turns
Keycloak Admin API resources into native Kubernetes custom resources. `kubectl apply`
a `KeycloakClient` (or realm, group, mapper, identity provider, authentication
flow, …) and KOG's [`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider)
and [`rest-dynamic-controller`](https://github.com/krateo-platformops/rest-dynamic-controller)
reconcile it against a running Keycloak. This is the **configuration** half of the
Keycloak↔Krateo↔OpenStack SSO work; the **lifecycle** half (installing Keycloak
itself) is the sibling
[`krateo-keycloak-blueprint`](https://github.com/krateo-blueprints/krateo-keycloak-blueprint).

The repo carries one Helm chart (`chart/`) plus the sibling
`CompositionDefinition` (`compositiondefinition.yaml`) that registers it with Krateo.

## The bundle (start here)

- [overview](./overview.md) — the KOG mechanics, the two design decisions (patched
  `securitySchemes`, ESO-minted short-lived token), the delegated executions surface.
- [usage](./usage.md) — install via Helm or as a Krateo Composition, wire the admin
  token, apply the sample CRs, watch reconcile.
- [configuration](./configuration.md) — the whole `values.yaml` surface: target,
  auth/ESO, which RestDefinitions to emit, Snowplow delegation.
- [api](./api.md) — the `CompositionDefinition` CRD this blueprint registers, and
  the generated resource kinds it produces.
- [examples](./examples.md) — the runnable example under `examples/`.
- [release](./release.md) — how a release ships (SemVer tag → chart on GHCR).
- [log](./log.md) — curated history.
- [llms.txt](./llms.txt) — the version-pinned doc index of this bundle.

## Layout

- `chart/` — the blueprint chart: `templates/rd-*.yaml` (one `RestDefinition` per
  Keycloak resource), `templates/configmaps.yaml` (embeds the curated OAS assets),
  `templates/externalsecret.yaml` (ESO admin-token wiring),
  `templates/restactions-authenticationexecution.yaml` (the delegated exec surface),
  `assets/*.yaml` (the hand-curated OAS subsets), `values.yaml`,
  `values.schema.json`.
- `compositiondefinition.yaml` — this blueprint's own registration.
- `samples/` — ready-to-edit CRs (`00-configurations.yaml`, `10-sso-realm.yaml`,
  `20-authentication-mfa.yaml`).
- `examples/` — a runnable Composition manifest (`composition.yaml`).
- `demo/`, `tests/`, `hack/` — end-to-end walkthroughs, the offline delegation-wiring
  tests, and the OAS-asset generator.

## Design & reference

- [ARCHITECTURE.md](./ARCHITECTURE.md) — the full design of the two-deliverable
  Keycloak/Krateo/OpenStack SSO story and the authentication-flow delegation model.
