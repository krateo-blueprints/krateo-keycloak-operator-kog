---
type: Example
title: sso-realm — an end-to-end SSO realm as Keycloak-config-KOG CRs
description: A runnable example that provisions a Krateo/OpenStack shared-session SSO realm — realm, groups mapper, keystone and krateo-authn OIDC clients, and an OpenStack project group — entirely as keycloak-config-kog custom resources.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [example, keycloak, sso, oidc]
timestamp: 2026-08-11T00:00:00Z
---

# sso-realm

An end-to-end SSO setup expressed purely as keycloak-config-kog custom resources. It
provisions everything the Krateo + OpenStack Horizon shared-session SSO needs:

- a `krateo` realm (`KeycloakRealm`),
- a `groups` Group Membership protocol mapper — declared **inline** on the client,
  consumed identically by Krateo authn (`additionalScopes: groups`) and the Keystone
  OIDC mapping rules,
- the `keystone` OIDC client (Horizon/Keystone federation RP),
- the `krateo-authn` OIDC client (Krateo portal login),
- one example OpenStack project group (`KeycloakGroup`) whose membership drives
  Keystone authz.

The manifests referenced here live at the repo root so they stay in sync with the
validated end-to-end walkthrough:

- [`../../samples/00-configurations.yaml`](../../samples/00-configurations.yaml) — the
  per-Kind `<Kind>Configuration` CRs, all pointing at the ESO-managed
  `keycloak-admin-token` Secret.
- [`../../samples/10-sso-realm.yaml`](../../samples/10-sso-realm.yaml) — the realm,
  clients, inline `groups` mapper and project group above.

## Run it

Preconditions: the chart is installed (`RestDefinition`s registered, CRDs generated),
Keycloak is reachable at `keycloak.baseUrl`, and the ESO admin-token path is working
([usage](../../docs/usage.md)).

```console
# 1) One <Kind>Configuration per resource → the shared bearer token Secret.
$ kubectl apply -f ../../samples/00-configurations.yaml

# 2) The SSO realm, clients, inline groups mapper and project group.
#    Replace <KRATEO_HOST> / <KEYSTONE_HOST> with your ingress hostnames first.
$ kubectl apply -f ../../samples/10-sso-realm.yaml

# 3) Watch them reconcile into the real Keycloak.
$ kubectl -n krateo-system get keycloakrealms.keycloak.ogen.krateo.io \
    keycloakclients.keycloak.ogen.krateo.io -w
```

Each CR carries a `spec.configurationRef` pointing at the `keycloak-admin`
Configuration, so rest-dynamic-controller authenticates with the rotated admin bearer
token. When the clients report `Ready=True` they exist in Keycloak with the `groups`
claim wired for both Krateo and Keystone federation.

For the Composition form of the install (a single `KeycloakConfigKog` CR instead of a
`helm install`), see [`../composition.yaml`](../composition.yaml) and
[examples](../../docs/examples.md). For the MFA/ACR step-up ladder, apply
[`../../samples/20-authentication-mfa.yaml`](../../samples/20-authentication-mfa.yaml).
