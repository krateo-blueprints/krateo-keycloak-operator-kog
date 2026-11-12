---
type: Usage
title: keycloak-config-kog — usage
description: How to install the blueprint — via Helm or as a Krateo Composition — wire the ESO admin token, apply the sample CRs (configurations, SSO realm, MFA ladder), and watch reconcile.
resource: oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog
tags: [keycloak, install, helm, composition, eso]
timestamp: 2026-08-11T00:00:00Z
---

# Usage

## Prerequisites

- A running Keycloak (the sibling
  [`krateo-keycloak-blueprint`](https://github.com/krateo-blueprints/krateo-keycloak-blueprint)
  stands one up), reachable at `keycloak.baseUrl`.
- The KOG toolchain: `oasgen-provider` and `rest-dynamic-controller` installed in the
  cluster (`oasgen-provider` 0.12.0+ / rdc 0.11.0+ are the versions validated
  in-cluster; the `KeycloakUser` resource needs oasgen-provider (and its bundled
  rest-dynamic-controller) **>= 0.56.0** — see the notes in
  `helm/keycloak-config-kog/templates/rd-user.yaml`).
- [External Secrets Operator](https://external-secrets.io) ≥ 0.19 for the default
  short-lived-token wiring.
- A service-account client in Keycloak (`krateo-kog` by default) with
  `serviceAccountsEnabled` and the `realm-management` roles for the resources you
  manage.
- For the `KeycloakAuthenticationExecution` surface only: Snowplow + authn wired into
  the rdc deployment (`URL_SNOWPLOW`/`URL_AUTHN` + a projected authn token).

## Install with Helm

```console
$ helm install oasgen-provider krateo/oasgen-provider -n krateo-system --create-namespace

# Pre-create the service-account client secret ESO uses to mint admin tokens.
# The Secret must carry the ESO webhook label or ESO refuses to read it.
$ kubectl -n krateo-system create secret generic keycloak-kog-client \
    --from-literal=clientSecret='<krateo-kog client secret>'
$ kubectl -n krateo-system label secret keycloak-kog-client external-secrets.io/type=webhook

$ helm install keycloak-config-kog ./chart -n krateo-system \
    --set keycloak.baseUrl=https://<KEYCLOAK_HOST>
```

Or from the published OCI chart:

```console
$ helm install keycloak-config-kog \
    oci://ghcr.io/krateo-blueprints/charts/keycloak-config-kog \
    --version <X.Y.Z> -n krateo-system \
    --set keycloak.baseUrl=https://<KEYCLOAK_HOST>
```

## Install as a Krateo Composition

The blueprint registers itself with Krateo through `compositiondefinition.yaml`. Once
the `CompositionDefinition` is applied (its Kind is `KeycloakConfigKog`, derived from
the chart name), install a Composition instance — the runnable manifest is
`examples/composition.yaml` ([examples](./examples.md)):

```console
$ kubectl apply -f compositiondefinition.yaml
$ kubectl apply -f examples/composition.yaml
```

See [api](./api.md) for the `CompositionDefinition` CRD contract and the
value-to-CRD derivation.

## Apply the resource CRs

Installing the chart registers the `RestDefinition`s and generates the CRDs; it does
**not** create any Keycloak resources. Apply your own CRs once the CRDs exist. The
`samples/` are ready to edit:

```console
# 1) One <Kind>Configuration per resource, all pointing at the ESO-managed
#    keycloak-admin-token Secret.
$ kubectl apply -f samples/00-configurations.yaml

# 2) An end-to-end SSO realm: krateo realm + groups mapper + keystone and
#    krateo-authn clients + an OpenStack project group.
$ kubectl apply -f samples/10-sso-realm.yaml

# 3) (optional) The MFA step-up ladder: OTP/WebAuthn realm policy, required
#    actions, a browser flow, its executions, and the acr.loa.map client.
$ kubectl apply -f samples/20-authentication-mfa.yaml

$ kubectl -n krateo-system get keycloakclients.keycloak.ogen.krateo.io -w
```

Each CR references a `<Kind>Configuration` (`configurationRef`) that carries the
bearer `tokenRef` — the ESO-rotated `keycloak-admin-token` Secret. Replace the
`<KRATEO_HOST>` / `<KEYSTONE_HOST>` / `<APP_HOST>` placeholders in the samples with
your real ingress hostnames.

## Realm outgoing mail, events and action links (0.6.0)

`KeycloakRealm` carries the realm's SMTP server, its user-event settings and the lifetime of the
action links Keycloak emails (set-password, verify-email). The SMTP **user and password never sit in
the CR**: `smtpCredentialsRef` names one Secret in the CR's own namespace, and the controller writes
its two keys into `smtpServer.user` / `smtpServer.password` on create and update.

```yaml
apiVersion: keycloak.ogen.krateo.io/v1
kind: KeycloakRealm
metadata:
  name: krateo
  namespace: krateo-system
spec:
  configurationRef:
    name: keycloak-admin
    namespace: krateo-system
  realm: krateo
  registrationAllowed: false
  resetPasswordAllowed: true
  verifyEmail: true
  actionTokenGeneratedByAdminLifespan: 259200   # seconds; the set-password link stays valid 72 h
  eventsEnabled: true
  enabledEventTypes: [LOGIN, LOGIN_ERROR, UPDATE_CREDENTIAL]
  eventsListeners: [jboss-logging]
  smtpServer:                                   # every value is a string, as Keycloak stores it
    host: smtp-relay.gmail.com
    port: "587"
    from: noreply@example.com
    auth: "true"
    starttls: "true"
    ssl: "false"
  smtpCredentialsRef:                           # Secret keys, not values
    name: keycloak-smtp
    userKey: username
    passwordKey: password
```

What was measured live (Keycloak 26.4 via keycloak-operator, rest-dynamic-controller 0.59.0):

- The realm holds exactly the CR: the SMTP user equals the Secret's key. Keycloak returns the
  password masked (`**********`), so it is never compared, and an idle realm is never re-PUT
  (no `UPDATE REALM` admin events across several resyncs).
- A realm PUT that echoes the masked value back does **not** overwrite the stored password.
- With a wrong password, `PUT .../users/{id}/execute-actions-email` answers **HTTP 500**, nothing is
  sent, and the server log reports `KC-SERVICES0029 ... AuthenticationFailedException`.

**An email an administrator triggers (the admin API's execute-actions-email) records no user event**,
whether it succeeds or fails. Success appears only as an admin event (`ACTION` on `USER`); a failed
send records nothing. Whoever calls the admin API must treat a non-204 answer as the failure signal.
(Up to 0.7.0 this page, and krateo-keycloak-realm up to 0.3.0, named `SEND_EXECUTE_ACTIONS` and
`SEND_ERROR`: neither is a Keycloak EventType. Keycloak stored them, recorded nothing, and answered
HTTP 500 to event queries by them.)

### Rotating SMTP credentials

A change to the Secret's content alone does **not** reach Keycloak. A secretRef-resolved value is
assembled into the request body and never becomes part of the CR, so drift detection never compares
it (whether or not Keycloak masks it): the controller sends the current Secret value only when some
other spec change triggers an update. Measured: the old password stayed in Keycloak after two
resyncs, and the next spec change pushed the new one in a single PUT.

Rotate by creating a **new** Secret and pointing `smtpCredentialsRef.name` at it, then delete the old
Secret. The spec change bumps the CR's generation, and the controller re-sends with the new Secret's
values: measured between 2 seconds and about a minute after the change. Verify with a test email.
Never edit the referenced Secret in place: that change is invisible to the controller. This works on
every released rest-dynamic-controller version and holds for every other `*SecretRef` in this chart
(IdP and client secrets). Re-applying on a Secret content change is tracked upstream as
krateo-platformops/oasgen-provider#598.

### Token authentication (XOAUTH2), e.g. Microsoft 365

Providers that disable password SMTP AUTH (Microsoft 365 does, for SMTP client submission) need
Keycloak's token mode (Keycloak >= 26.2): Keycloak fetches an OAuth2 access token with the client
credentials grant and logs in with `AUTH XOAUTH2`. The Secret then carries the client secret instead
of a password:

```yaml
  smtpServer:
    host: smtp.office365.com
    port: "587"
    from: noreply@example.com
    auth: "true"                 # required in both modes
    starttls: "true"
    ssl: "false"
    authType: token              # basic (default) | token
    authTokenUrl: https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token
    authTokenClientId: <application (client) id>
    authTokenScope: https://outlook.office365.com/.default
  smtpCredentialsRef:
    name: keycloak-smtp
    userKey: username            # the sending mailbox: the XOAUTH2 user
    clientSecretKey: clientSecret
```

The scope Microsoft documents for SMTP client credentials is `https://outlook.office365.com/.default`;
the Keycloak server admin guide's example shows `https://outlook.office.com/.default`.

Measured against a token endpoint and an SMTP server that accept only `AUTH XOAUTH2` with the exact
token issued:

- Keycloak POSTs `grant_type=client_credentials` with the client id, the Secret's client secret and
  the scope, then logs in as `smtpServer.user` with that token. `authTokenClientSecret` reads back
  masked, like the password.
- Keycloak caches the token per realm and, when SMTP rejects it (e.g. revoked or expired), fetches a
  new one and retries once. An expired token therefore heals itself while the client secret is valid.
- A wrong client secret makes the token request fail (401) and execute-actions-email answer HTTP 500,
  with `KC-SERVICES0029 ... Connect failed for SMTP` in the server log.

Client secrets of Microsoft Entra applications **expire** (at most 24 months). Rotation is therefore
routine, not exceptional: create the new Secret and repoint the ref as described above, before the old
secret expires.

## Realm user profile (0.7.0)

Keycloak (24 and later) keeps one declarative **user profile** per realm: the list of user attributes
that exist, who may view and edit each one, and their validators. An attribute that the profile does
not declare is dropped when a user is created or updated (unless the realm's
`unmanagedAttributePolicy` opens undeclared attributes, which this kind leaves to you).

`KeycloakUserProfile` manages that document. It has no create and no delete verb: a realm always has
a profile, so the controller reads it (GET) and replaces it with the CR's (PUT) whenever they differ,
including after a change made in the admin console. Deleting the CR leaves the realm's profile as it
is. Because the document is replaced whole, **the CR owns the entire profile**: list every attribute
the realm keeps, the built-in `username`, `email`, `firstName` and `lastName` included, exactly as
Keycloak's default declares them, or existing users meet different rules on their next update.

```yaml
apiVersion: keycloak.ogen.krateo.io/v1
kind: KeycloakUserProfile
metadata:
  name: krateo-user-profile
  namespace: krateo-system
spec:
  configurationRef:
    name: keycloak-admin
    namespace: krateo-system
  realm: krateo
  attributes:
    # ...Keycloak's default username, email, firstName and lastName first, verbatim...
    - name: krateo-access-request-uid
      displayName: Access request
      permissions:
        view:
          - admin
        edit:
          - admin
      validations:
        length:
          max: 36
  groups:
    - name: user-metadata
      displayHeader: User metadata
      displayDescription: Attributes, which refer to user metadata
```

`permissions` take `admin` (the Admin API and console) and `user` (the user, in the account console
and on login pages). An attribute with `view` and `edit` set to `[admin]` is invisible to the user,
and the account API refuses a value the user sends for it (HTTP 400,
`error-user-attribute-read-only`) without touching the stored one. Keycloak fills `multivalued: false`
on attributes that omit it; the controller does not treat that default as drift. The validators are typed:
`length`, `email`, `pattern`, `options`, `uri`, `integer`, `double`, `local-date`, `iso-date`,
`multivalued`, `username-prohibited-characters`, `up-username-not-idn-homograph` and
`person-name-prohibited-characters`. A validator outside that list is pruned by the API server.

The [krateo-keycloak-realm](https://github.com/krateo-blueprints/krateo-keycloak-realm) chart
(0.3.0 and later) renders this CR from Keycloak's default profile plus its `userProfile.attributes`
values, so most installs never write it by hand.

## Verify the admin-token path

ESO mints a fresh admin bearer token from Keycloak's token endpoint into
`keycloak-admin-token`; rest-dynamic-controller reads it per reconcile:

```console
$ kubectl -n krateo-system get externalsecret keycloak-admin-token
$ kubectl -n krateo-system get secret keycloak-admin-token -o jsonpath='{.data.token}' | base64 -d | cut -c1-20
```

If a CR stalls `Ready=False`, check the rdc logs and confirm the token Secret is
being refreshed (a stale token surfaces as 401s from the Admin API).

## The OAS assets

`helm/keycloak-config-kog/assets/<key>.yaml` is the hand-curated OpenAPI 3.0 subset each kind is
generated from, and it is the source of truth: edit it to change a kind's field surface. Field names
stay verbatim from Keycloak's official OAS so request bodies remain wire-compatible. (Until 0.7.0 the
README pointed at a generator script, `hack/gen_oas_assets.py`; it had stopped matching the shipped
assets several releases earlier and was removed.)
