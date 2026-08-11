---
type: Runbook
title: keycloak-config-kog — release
description: How a release ships — a SemVer git tag matching Chart.yaml publishes the chart to GHCR OCI, after which the CompositionDefinition is bumped to the published version.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [release, oci, ghcr, helm]
timestamp: 2026-08-11T00:00:00Z
---

# Release

One SemVer git tag (`X.Y.Z`, **no** `v` prefix, matching `chart/Chart.yaml`'s
`version`) publishes the chart. The tag push triggers `release-chart.yaml`.

## What a tag ships

`release-chart.yaml` (`.github/workflows/release-chart.yaml`) on a
`[0-9]+.[0-9]+.[0-9]+` tag:

1. `helm lint chart` — validates the chart and its `values.schema.json`.
2. Verifies the git tag equals `Chart.yaml`'s `version` (fails the release
   otherwise).
3. `helm package chart` — `helm package` does not render templates, so a chart that
   needs runtime input still publishes.
4. Logs in to GHCR with the workflow `GITHUB_TOKEN`.
5. `helm push` to `oci://ghcr.io/<owner>/charts` (the owner is derived from the
   repository, lower-cased — `GITHUB_TOKEN` can only write its own namespace), with a
   5-attempt retry for GHCR first-push flakiness.

The published artifact is `oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog`,
which is exactly what `compositiondefinition.yaml`'s `spec.chart.url` points at.

## Steps

```console
$ git tag X.Y.Z && git push origin X.Y.Z
```

Then verify the artifact exists:

```console
$ helm show chart oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog \
    --version X.Y.Z | head -3
```

After the chart is published, bump `compositiondefinition.yaml`'s
`spec.chart.version` to `X.Y.Z` on `main` — it is this blueprint's own registration
and must point at a version that exists.

## PR-time checks

Two workflows run on every PR and push to `main`:

- **`chart-tests.yaml`** — `helm lint` + `helm template` (the render must succeed),
  a check that every embedded `chart/assets/*.yaml` OAS parses, and the
  `KeycloakAuthenticationExecution` **delegation-wiring tests** (`tests/delegation`),
  which render the chart, extract the exact jq from the four Snowplow `RESTAction`s,
  and assert the observe/create/update/delete stages against fixture payloads. Fully
  offline — no Keycloak, no cluster.
- **`lint.yaml`** — the shared Krateo docs-standard linter (`lint-docs`), which checks
  this documentation bundle for the invariant core files, valid frontmatter,
  resolvable links, and the README section order.

Live-Keycloak validation is a separately-gated step: `hack/validate-executions-live.sh`
replays the extracted stage sequences against a real Keycloak, and the full in-cluster
reconcile is exercised by the `demo/` walkthroughs.

## Version pinning downstream

Consumers install by explicit `--version`; the `CompositionDefinition` pins the exact
published chart. Nothing tracks a mutable `latest` tag.
