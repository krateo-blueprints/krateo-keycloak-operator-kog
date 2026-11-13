#!/usr/bin/env python3
"""Live audit: does Keycloak actually return every additionalStatusField the RestDefinitions declare?

rest-dynamic-controller copies each declared status field out of the observe response and skips a
field that is absent WITHOUT any error, event or log line, so a field the server never returns looks
exactly like a working one on a Ready CR (reported across KOGs: a Nova field gated behind a
microversion). The OAS and the RestDefinition can agree with each other and both be wrong about the
server. This audit asks the server.

It renders the chart, reads each non-delegated kind's additionalStatusFields and its get/findby paths
from the rendered RestDefinitions (nothing duplicated here), creates one object per kind in a scratch
realm, and checks every declared field in the get response and in the findby item that matches.
Delegated kinds (observeApiRef) compose their status in a RESTAction and are covered by
tests/delegation instead.

Usage: KC_URL=http://127.0.0.1:<port> KC_ADMIN_PASS_FILE=<file> python3 hack/audit-status-fields-live.py
Exit 0 = every declared field is returned (or explicitly listed as conditional below).
"""
import json, os, shutil, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request
import yaml

KC = os.environ.get("KC_URL", "http://localhost:8081").rstrip("/")
PASS = open(os.environ["KC_ADMIN_PASS_FILE"]).read()
REALM = "kog-status-audit"
# Fields Keycloak returns only once they are set. Listing one here is a decision, recorded with why.
CONDITIONAL = {
    ("KeycloakUserProfile", "unmanagedAttributePolicy"):
        "Keycloak omits it from GET /users/profile until a policy is set; unset means 'unmanaged attributes disabled'.",
}


def render():
    work = tempfile.mkdtemp(prefix="audit-")
    try:
        shutil.copytree("helm/keycloak-config-kog", f"{work}/c")
        cy = f"{work}/c/Chart.yaml"
        text = open(cy).read()
        open(cy, "w").write(text.replace("CHART_VERSION", "0.0.0-audit"))
        out = subprocess.run(["helm", "template", "t", f"{work}/c"], capture_output=True, text=True, check=True).stdout
        return [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "RestDefinition"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def token():
    body = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": PASS}).encode()
    return json.load(urllib.request.urlopen(KC + "/realms/master/protocol/openid-connect/token", data=body))["access_token"]


def call(method, path, body=None):
    req = urllib.request.Request(KC + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None), r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200], ""


def created_id(location):
    return location.rstrip("/").rsplit("/", 1)[-1]


def dig(obj, dotted):
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return False, None
        obj = obj[part]
    return True, obj


def main():
    rds = {d["spec"]["resource"]["kind"]: d["spec"]["resource"] for d in render()}
    R = f"/admin/realms/{REALM}"
    call("DELETE", R)
    assert call("POST", "/admin/realms", {"realm": REALM, "enabled": True})[0] == 201
    p = {"realm": REALM}
    # One object per kind; record the path parameters each kind's get needs.
    params = {"KeycloakRealm": dict(p)}
    _, _, loc = call("POST", f"{R}/clients", {"clientId": "audit-client", "publicClient": True})
    cid = created_id(loc); params["KeycloakClient"] = dict(p, id=cid)
    _, _, loc = call("POST", f"{R}/client-scopes", {"name": "audit-scope", "protocol": "openid-connect"})
    params["KeycloakClientScope"] = dict(p, id=created_id(loc))
    _, _, loc = call("POST", f"{R}/groups", {"name": "audit-group"})
    params["KeycloakGroup"] = dict(p, id=created_id(loc))
    _, _, loc = call("POST", f"{R}/users", {"username": "audit-user", "enabled": True})
    params["KeycloakUser"] = dict(p, id=created_id(loc))
    call("POST", f"{R}/identity-provider/instances", {"alias": "audit-idp", "providerId": "oidc", "enabled": True,
         "config": {"clientId": "x", "clientSecret": "y", "authorizationUrl": "https://idp.example.test/auth",
                    "tokenUrl": "https://idp.example.test/token", "clientAuthMethod": "client_secret_post"}})
    params["KeycloakIdentityProvider"] = dict(p, alias="audit-idp")
    _, _, loc = call("POST", f"{R}/identity-provider/instances/audit-idp/mappers",
                     {"name": "audit-mapper", "identityProviderAlias": "audit-idp", "identityProviderMapper": "hardcoded-attribute-idp-mapper",
                      "config": {"attribute": "a", "attribute.value": "b", "syncMode": "INHERIT"}})
    params["KeycloakIdentityProviderMapper"] = dict(p, alias="audit-idp", id=created_id(loc))
    _, _, loc = call("POST", f"{R}/clients/{cid}/protocol-mappers/models",
                     {"name": "audit-pm", "protocol": "openid-connect", "protocolMapper": "oidc-hardcoded-claim-mapper",
                      "config": {"claim.name": "c", "claim.value": "v", "access.token.claim": "true"}})
    params["KeycloakProtocolMapper"] = dict(p, clientUuid=cid, id=created_id(loc))
    _, _, loc = call("POST", f"{R}/authentication/flows", {"alias": "audit-flow", "providerId": "basic-flow", "topLevel": True, "builtIn": False})
    params["KeycloakAuthenticationFlow"] = dict(p, id=created_id(loc))
    params["KeycloakUserProfile"] = dict(p)
    params["KeycloakRequiredAction"] = dict(p, alias="CONFIGURE_TOTP")

    fails, rows = [], []
    for kind, res in sorted(rds.items()):
        if "observeApiRef" in res:
            rows.append(f"  skip  {kind}: delegated (status composed by RESTAction; tests/delegation)")
            continue
        fields = res.get("additionalStatusFields") or []
        if not fields:
            rows.append(f"  --    {kind}: no additionalStatusFields")
            continue
        verbs = {v["action"]: v for v in res["verbsDescription"]}
        pr = params[kind]
        gpath = verbs["get"]["path"]
        for k, v in pr.items():
            gpath = gpath.replace("{" + k + "}", v)
        st, got, _ = call("GET", gpath)
        item = None
        if "findby" in verbs and isinstance(got, dict):
            fpath = verbs["findby"]["path"]
            for k, v in pr.items():
                fpath = fpath.replace("{" + k + "}", v)
            _, lst, _ = call("GET", fpath)
            if isinstance(lst, list):
                ident = next((i for i in (res.get("identifiers") or []) if i in got), None)
                item = next((x for x in lst if ident and x.get(ident) == got.get(ident)), None)
        for f in fields:
            in_get, val = dig(got if isinstance(got, dict) else {}, f)
            in_find = None if item is None else dig(item, f)[0]
            cond = CONDITIONAL.get((kind, f))
            ok = in_get and (in_find in (None, True))
            tag = "ok   " if ok else ("cond " if cond else "FAIL ")
            rows.append(f"  {tag} {kind}.{f}: get={'present' if in_get else 'ABSENT'} (HTTP {st})"
                        + ("" if in_find is None else f", findby item={'present' if in_find else 'ABSENT'}")
                        + (f"  [{cond}]" if cond and not ok else ""))
            if not ok and not cond:
                fails.append(f"{kind}.{f}")
    print("\n".join(rows))
    call("DELETE", R)
    print()
    if fails:
        print(f"STATUS FIELDS NEVER RETURNED: {fails}")
        sys.exit(1)
    print("Every declared status field is returned by this Keycloak (conditional ones listed above).")


if __name__ == "__main__":
    main()
