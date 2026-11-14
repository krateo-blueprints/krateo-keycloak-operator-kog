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

Every field gets exactly one verdict:
  ok             present in the get response and in the findby item; findby is NOT-CHECKED only when the
                 kind has no findby verb or the response carries no identifier to match on
  ABSENT         the server answered 200 and the field is not there              -> fails
  NOT-MEASURED   the question failed (non-2xx get or findby, unresolved path parameter) -> fails: a
                 failed question is not a negative answer, and not a positive one either
  FINDBY-MISS    the object is not exactly once in its own findby listing          -> fails (adoption would
                 create or duplicate)
  cond           listed in CONDITIONAL and absent, as the exemption predicts
  STALE          listed in CONDITIONAL but present: the exemption no longer holds -> fails
The run fails when any field is ABSENT / NOT-MEASURED / STALE, when a non-delegated kind has no fixture,
or when it checked zero fields (a fleet zero means nothing). `--selftest` drives each verdict through
synthetic responses, offline, and prints what it ran.

Usage: KC_URL=http://127.0.0.1:<port> KC_ADMIN_PASS_FILE=<file> python3 hack/audit-status-fields-live.py
       python3 hack/audit-status-fields-live.py --selftest
"""
import json, os, shutil, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request
import yaml

REALM = "kog-status-audit"
# Fields Keycloak returns only once they are set. Listing one here is a decision, recorded with why, and
# it is re-validated every run: a listed field that comes back present fails as STALE.
CONDITIONAL = {
    ("KeycloakUserProfile", "unmanagedAttributePolicy"):
        "Keycloak omits it from GET /users/profile until a policy is set; unset means 'unmanaged attributes disabled'.",
}


def dig(obj, dotted):
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return False
        obj = obj[part]
    return True


def substitute(path, params):
    for k, v in params.items():
        path = path.replace("{" + k + "}", v)
    return path


def audit_kind(kind, res, params, call):
    """-> list of (verdict, row). Pure apart from `call(method, path) -> (status, body)`."""
    fields = res.get("additionalStatusFields") or []
    verbs = {v["action"]: v for v in res["verbsDescription"]}
    out = []
    gpath = substitute(verbs["get"]["path"], params)
    if "{" in gpath:
        return [("NOT-MEASURED", f"{kind}.{f}: get path still has an unresolved parameter: {gpath}") for f in fields]
    st, got = call("GET", gpath)
    if not (200 <= st < 300) or not isinstance(got, dict):
        return [("NOT-MEASURED", f"{kind}.{f}: get answered HTTP {st} ({type(got).__name__}), so nothing was measured")
                for f in fields]
    # findby: locate the item matching the object by one of the kind's identifiers.
    # A NOT-CHECKED excuse must be a property of the definition (no findby verb) or of the response (no
    # identifier to match on), never of a failed request: that is NOT-MEASURED, as on the get side. An
    # object missing from its own findby listing is a negative answer (FINDBY-MISS): it is how adoption
    # fails, and with one object per kind in a scratch realm pagination cannot explain it.
    find_item, find_why = None, None
    if "findby" not in verbs:
        find_why = "kind has no findby verb"
    else:
        fpath = substitute(verbs["findby"]["path"], params)
        ident = next((i for i in (res.get("identifiers") or []) if i in got), None)
        if "{" in fpath:
            return [("NOT-MEASURED", f"{kind}.{f}: findby path still has an unresolved parameter: {fpath}") for f in fields]
        if ident is None:
            find_why = f"none of the identifiers {res.get('identifiers')} is in the get response"
        else:
            fst, lst = call("GET", fpath)
            if not (200 <= fst < 300) or not isinstance(lst, list):
                return [("NOT-MEASURED", f"{kind}.{f}: findby answered HTTP {fst} ({type(lst).__name__}), so it was not measured")
                        for f in fields]
            matches = [x for x in lst if isinstance(x, dict) and x.get(ident) == got.get(ident)]
            if len(matches) != 1:
                return [("FINDBY-MISS", f"{kind}.{f}: findby listing has {len(matches)} item(s) with {ident}={got.get(ident)!r}, "
                                        f"want exactly 1 (adoption would create or duplicate)") for f in fields]
            find_item = matches[0]
    for f in fields:
        in_get = dig(got, f)
        if find_item is not None:
            in_find, find_txt = dig(find_item, f), ("present" if dig(find_item, f) else "ABSENT")
        else:
            in_find, find_txt = None, f"NOT-CHECKED({find_why})"
        cond = CONDITIONAL.get((kind, f))
        row = f"{kind}.{f}: get={'present' if in_get else 'ABSENT'} (HTTP {st}), findby={find_txt}"
        if cond:
            if in_get or in_find:
                out.append(("STALE", row + f"  [listed as conditional but returned: drop the exemption: {cond}]"))
            else:
                out.append(("cond", row + f"  [{cond}]"))
        elif in_get and in_find is not False:
            out.append(("ok", row))
        else:
            out.append(("ABSENT", row))
    return out


FAILING = {"ABSENT", "NOT-MEASURED", "STALE", "FINDBY-MISS"}


def summarize(results, n_kinds, delegated, none_declared, missing_fixtures):
    """Print the verdict rows and the denominator; return the exit code."""
    for v, row in results:
        print(f"  {v:<13} {row}")
    checked = len(results)
    bad = [r for v, r in results if v in FAILING]
    print()
    print(f"checked {checked} field(s) across {n_kinds} non-delegated kind(s) ({len(delegated)} delegated: "
          f"{', '.join(sorted(delegated)) or '-'}; {len(none_declared)} declaring none: {', '.join(sorted(none_declared)) or '-'})")
    if missing_fixtures:
        print(f"UNAUDITED: no fixture for {sorted(missing_fixtures)}; add one to the audit")
    if checked == 0:
        print("CHECKED ZERO FIELDS: the render or the walk is broken; a fleet zero is not a pass")
    if bad:
        print(f"FAILED: {len(bad)} field(s) ABSENT / NOT-MEASURED / STALE / FINDBY-MISS")
    if bad or missing_fixtures or checked == 0:
        return 1
    print("Every declared status field is returned by this Keycloak (conditional ones listed above).")
    return 0


# ------------------------------------------------------------------------------------- live run

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


def live():
    kc = os.environ.get("KC_URL", "http://localhost:8081").rstrip("/")
    password = open(os.environ["KC_ADMIN_PASS_FILE"]).read()

    def token():
        body = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli", "username": "admin",
                                       "password": password}).encode()
        return json.load(urllib.request.urlopen(kc + "/realms/master/protocol/openid-connect/token", data=body))["access_token"]

    def raw(method, path, body=None):
        req = urllib.request.Request(kc + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json",
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                text = r.read().decode()
                return r.status, (json.loads(text) if text.strip() else None), r.headers.get("Location", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:200], ""

    def created(st, loc, what):
        if st != 201 or not loc:
            raise RuntimeError(f"fixture {what}: HTTP {st}")
        return loc.rstrip("/").rsplit("/", 1)[-1]

    rds = {d["spec"]["resource"]["kind"]: d["spec"]["resource"] for d in render()}
    delegated = {k for k, r in rds.items() if "observeApiRef" in r}
    none_declared = {k for k, r in rds.items() if k not in delegated and not r.get("additionalStatusFields")}
    audited = set(rds) - delegated - none_declared
    fixtures = {"KeycloakRealm", "KeycloakClient", "KeycloakClientScope", "KeycloakGroup", "KeycloakUser",
                "KeycloakIdentityProvider", "KeycloakIdentityProviderMapper", "KeycloakProtocolMapper",
                "KeycloakAuthenticationFlow", "KeycloakUserProfile"}
    # Reconciled BEFORE creating anything: a new or renamed kind is reported, not a mid-run crash.
    missing = audited - fixtures
    R = f"/admin/realms/{REALM}"
    results = []
    raw("DELETE", R)
    try:
        st, _, _ = raw("POST", "/admin/realms", {"realm": REALM, "enabled": True})
        if st != 201:
            raise RuntimeError(f"fixture realm: HTTP {st}")
        p = {"realm": REALM}
        params = {"KeycloakRealm": dict(p), "KeycloakUserProfile": dict(p)}
        st, _, loc = raw("POST", f"{R}/clients", {"clientId": "audit-client", "publicClient": True})
        cid = created(st, loc, "client"); params["KeycloakClient"] = dict(p, id=cid)
        st, _, loc = raw("POST", f"{R}/client-scopes", {"name": "audit-scope", "protocol": "openid-connect"})
        params["KeycloakClientScope"] = dict(p, id=created(st, loc, "client scope"))
        st, _, loc = raw("POST", f"{R}/groups", {"name": "audit-group"})
        params["KeycloakGroup"] = dict(p, id=created(st, loc, "group"))
        st, _, loc = raw("POST", f"{R}/users", {"username": "audit-user", "enabled": True})
        params["KeycloakUser"] = dict(p, id=created(st, loc, "user"))
        st, _, _ = raw("POST", f"{R}/identity-provider/instances", {
            "alias": "audit-idp", "providerId": "oidc", "enabled": True,
            "config": {"clientId": "x", "clientSecret": "y", "authorizationUrl": "https://idp.example.test/auth",
                       "tokenUrl": "https://idp.example.test/token", "clientAuthMethod": "client_secret_post"}})
        if st != 201:
            raise RuntimeError(f"fixture identity provider: HTTP {st}")
        params["KeycloakIdentityProvider"] = dict(p, alias="audit-idp")
        st, _, loc = raw("POST", f"{R}/identity-provider/instances/audit-idp/mappers", {
            "name": "audit-mapper", "identityProviderAlias": "audit-idp", "identityProviderMapper": "hardcoded-attribute-idp-mapper",
            "config": {"attribute": "a", "attribute.value": "b", "syncMode": "INHERIT"}})
        params["KeycloakIdentityProviderMapper"] = dict(p, alias="audit-idp", id=created(st, loc, "idp mapper"))
        st, _, loc = raw("POST", f"{R}/clients/{cid}/protocol-mappers/models", {
            "name": "audit-pm", "protocol": "openid-connect", "protocolMapper": "oidc-hardcoded-claim-mapper",
            "config": {"claim.name": "c", "claim.value": "v", "access.token.claim": "true"}})
        params["KeycloakProtocolMapper"] = dict(p, clientUuid=cid, id=created(st, loc, "protocol mapper"))
        st, _, loc = raw("POST", f"{R}/authentication/flows", {"alias": "audit-flow", "providerId": "basic-flow",
                                                              "topLevel": True, "builtIn": False})
        params["KeycloakAuthenticationFlow"] = dict(p, id=created(st, loc, "authentication flow"))

        def call(method, path):
            st, body, _ = raw(method, path)
            return st, body
        for kind in sorted(audited - missing):
            results += audit_kind(kind, rds[kind], params[kind], call)
    finally:
        raw("DELETE", R)   # always, including after a fixture failure or a crash mid-audit
    return summarize(results, len(audited), delegated, none_declared, missing)


# ------------------------------------------------------------------------------------- self-test

def selftest():
    """Drive every verdict through synthetic responses, through the same audit_kind/summarize."""
    res = {"additionalStatusFields": ["id"], "identifiers": ["name"],
           "verbsDescription": [{"action": "get", "path": "/r/{realm}/x/{id}"},
                                {"action": "findby", "path": "/r/{realm}/x"}]}
    obj = {"id": "1", "name": "n"}
    pr = {"realm": "r", "id": "1"}

    def fake(get, find):
        return lambda m, path: get if "/x/" in path else find
    cases = [
        ("present in get and findby -> ok", "K", res, pr, fake((200, obj), (200, [obj])), "ok"),
        ("absent from a 200 get -> ABSENT", "K", res, pr, fake((200, {"name": "n"}), (200, [obj])), "ABSENT"),
        ("absent from the findby item -> ABSENT", "K", res, pr, fake((200, obj), (200, [{"name": "n"}])), "ABSENT"),
        ("get 404 -> NOT-MEASURED, not ABSENT", "K", res, pr, fake((404, "not found"), (200, [obj])), "NOT-MEASURED"),
        ("unresolved path parameter -> NOT-MEASURED", "K", res, {"realm": "r"}, fake((200, obj), (200, [obj])), "NOT-MEASURED"),
        ("findby 500 -> NOT-MEASURED (a failed request is never an excuse)", "K", res, pr, fake((200, obj), (500, "boom")), "NOT-MEASURED"),
        ("object missing from its own findby listing -> FINDBY-MISS", "K", res, pr, fake((200, obj), (200, [{"id": "2", "name": "other"}])), "FINDBY-MISS"),
        ("two findby items match -> FINDBY-MISS (duplicate)", "K", res, pr, fake((200, obj), (200, [obj, obj])), "FINDBY-MISS"),
        ("no identifier in the get response -> ok, findby NOT-CHECKED", "K", res, pr, fake((200, {"id": "1"}), (200, [obj])), "ok"),
        ("kind without a findby verb -> ok, findby NOT-CHECKED", "K", dict(res, verbsDescription=res["verbsDescription"][:1]), pr, fake((200, obj), (500, "never called")), "ok"),
        ("conditional and absent -> cond", "KeycloakUserProfile",
         dict(res, additionalStatusFields=["unmanagedAttributePolicy"]), pr, fake((200, obj), (200, [obj])), "cond"),
        ("conditional but present -> STALE", "KeycloakUserProfile",
         dict(res, additionalStatusFields=["unmanagedAttributePolicy"]), pr,
         fake((200, dict(obj, unmanagedAttributePolicy="ENABLED")), (200, [obj])), "STALE"),
    ]
    errors = []
    for desc, kind, r, p, call, want in cases:
        got = audit_kind(kind, r, p, call)
        verdict = got[0][0] if got else None
        if verdict != want:
            errors.append(f"self-test '{desc}': verdict {verdict}, want {want}: {got}")
    findby_skip = audit_kind("K", dict(res, verbsDescription=res["verbsDescription"][:1]), pr, fake((200, obj), (500, "x")))[0][1]
    if "NOT-CHECKED(kind has no findby verb)" not in findby_skip:
        errors.append(f"self-test: a findby that was not checked must say why: {findby_skip}")
    # Exit codes through the same summarize the live run uses (output suppressed).
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        zero = summarize([], 0, set(), set(), set())
        unaudited = summarize([("ok", "K.id")], 1, set(), set(), {"KeycloakNew"})
        clean = summarize([("ok", "K.id"), ("cond", "P.x")], 2, set(), set(), set())
    if zero != 1:
        errors.append("self-test: checking zero fields must fail")
    if unaudited != 1:
        errors.append("self-test: a kind with no fixture must fail")
    if clean != 0:
        errors.append("self-test: ok + cond must pass")
    for e in errors:
        print(f"::error::{e}")
    print(f"self-test: ran {len(cases)} verdict cases + findby-skip wording + 3 exit-code cases, {len(errors)} failure(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(selftest() if sys.argv[1:] == ["--selftest"] else live())
