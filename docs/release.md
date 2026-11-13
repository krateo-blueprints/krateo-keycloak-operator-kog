---
type: Runbook
title: keycloak-config-kog — release
description: How a release ships — a plain-SemVer git tag on a main commit that passed lint publishes the chart to GHCR OCI and to the Marketplace blueprints index, with the CompositionDefinition stamped to the tag inside the archive and on the GitHub release.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [release, oci, ghcr, helm, marketplace]
timestamp: 2026-11-12T00:00:00Z
---

# Release

One plain-SemVer git tag (`X.Y.Z`, **no** `v` prefix) publishes the chart. Nothing is bumped by
hand: `version: CHART_VERSION` in `helm/keycloak-config-kog/Chart.yaml` and
`spec.chart.version: CHART_VERSION` in the root `compositiondefinition.yaml` are stamped from the
tag. `appVersion` is the Keycloak release line the chart targets, not the chart version.

## Cut a release

1. Merge the change to `main`. [`lint.yaml`](../.github/workflows/lint.yaml) runs on the merge
   commit (it runs on every push to `main`).
2. Wait until that **whole** lint run has concluded successfully, then tag the merge commit:

   ```console
   $ git tag X.Y.Z <merge-sha> && git push origin X.Y.Z
   ```

## What a tag ships

[`release-tag.yaml`](../.github/workflows/release-tag.yaml), on a `[0-9]+.[0-9]+.[0-9]+` tag:

1. refuses the tag unless the tagged commit has a completed, successful run of `lint.yaml`;
2. stamps `CHART_VERSION` into `Chart.yaml` and the CompositionDefinition, and copies the stamped
   CompositionDefinition into the chart so the archive describes itself;
3. packages the chart and gates it for the Marketplace **blueprints** channel: `Chart.yaml`
   `sources` lists this repository, the archive carries `values.schema.json` and
   `compositiondefinition.yaml`, the CompositionDefinition installs this chart at this version,
   the icon is an https URL, and `keywords` is non-empty;
4. pushes it to `oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog` and checks that it is
   anonymously pullable (core-provider pulls anonymously);
5. attaches the stamped `compositiondefinition.yaml` to the GitHub release;
6. hands the same archive to the org publisher (`krateo-blueprints/charts` `publish-chart.yaml`),
   which adds it to `https://krateo-blueprints.github.io/charts/blueprints/index.yaml` and installs
   it from the served index before it reports success.

After publishing, pull `oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog --version X.Y.Z`
and compare its sha256 with the `digest` of the `X.Y.Z` entry in the blueprints index: they must
be the same bytes.

## PR-time checks

[`lint.yaml`](../.github/workflows/lint.yaml) runs on every PR and every push to `main`:

- **`test`** — the **delegation-wiring tests** of `KeycloakAuthenticationExecution` and
  `KeycloakServiceAccountRoleMapping` (`tests/delegation`): they render the chart, extract the exact
  jq from their Snowplow `RESTAction`s, and assert every stage and predicate against fixture payloads.
  Fully offline, no Keycloak, no cluster. This is the `test` check-run release consumers look for.
- **`lint`** — chart URL and status-field checks, a render with the keys added since 0.4.x absent
  (the `helm upgrade --reuse-values` shape), and the `values.schema.json` gate
  (`hack/check-schema-required.py`: no `required` key that `values.yaml` defaults).
- **`lint-docs`** — the shared Krateo docs-standard linter: invariant core files, valid
  frontmatter, resolvable links, README section order.

A full in-cluster reconcile against a real Keycloak is not part of CI; it is exercised by the
`demo/` walkthroughs and by the live validation recorded for each release in [log](log.md).

## Version pinning downstream

Consumers install by explicit `--version`; the `CompositionDefinition` pins the exact
published chart. Nothing tracks a mutable `latest` tag.
