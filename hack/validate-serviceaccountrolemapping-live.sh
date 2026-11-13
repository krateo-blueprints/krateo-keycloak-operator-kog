#!/usr/bin/env bash
# Live validation of the KeycloakServiceAccountRoleMapping reconcile semantics against a REAL Keycloak,
# without a cluster-side controller.
#
# What it does:
#   1. `helm template`s the chart and extracts the EXACT programs from the rendered RESTActions and
#      RestDefinition (stage paths, iterators, payloads, filters, notFoundExpr, upToDateExpr, the get
#      verb's notFoundBody).
#   2. Replays snowplow's stage semantics (extras-seeded dict, stages in order, iterator = one call per
#      element templated against the item only, a 2xx with an empty body is a stage error, which
#      continueOnError records under errorKey and otherwise ends the chain) and rest-dynamic-
#      controller's level-based loop (observe -> notFound ? create : upToDate ? done : update) with
#      urllib against a live Keycloak.
#   3. Asserts: a CR whose client does not exist yet stays not-found and mutates nothing; once the
#      client exists the exact role set converges; hand-made drift (an extra role, a removed role) is
#      reverted; a spec change converges; an unknown role name keeps the CR unready without blocking
#      the known ones; delete removes every role of the role-owning client and the get verification
#      reads the empty list as gone; a delete after the client is gone is a no-op and the get 404s.
#
# Prereqs: a reachable Keycloak whose master realm admin can log in (e.g. a start-dev pod behind a
# port-forward), helm, jq, python3 + pyyaml.
# Env: KC_URL (default http://localhost:8081), KC_ADMIN / KC_ADMIN_PASS, REALM (kog-sarm-validate).
set -euo pipefail
cd "$(dirname "$0")/.."

export KC_URL="${KC_URL:-http://localhost:8081}"
export KC_ADMIN="${KC_ADMIN:-admin}"
export KC_ADMIN_PASS="${KC_ADMIN_PASS:?set KC_ADMIN_PASS}"
export REALM="${REALM:-kog-sarm-validate}"
command -v helm >/dev/null || { echo "helm required"; exit 1; }
command -v jq >/dev/null || { echo "jq required"; exit 1; }

# Render a stamped copy, exactly as lint.yaml does, so the working tree is never modified.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -R helm/keycloak-config-kog "$WORK/chart"
sed -i.bak "s/CHART_VERSION/0.0.0-validate/g" "$WORK/chart/Chart.yaml"
export RENDERED="$WORK/rendered.yaml"
helm template kog "$WORK/chart" --namespace kog > "$RENDERED"

python3 - <<'PYEOF'
import json, os, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
import yaml

KC = os.environ["KC_URL"].rstrip("/")
REALM = os.environ["REALM"]
docs = [d for d in yaml.safe_load_all(open(os.environ["RENDERED"])) if d]
RA = {d["metadata"]["name"].rsplit("-", 1)[-1]: d["spec"] for d in docs
      if d.get("kind") == "RESTAction" and "-serviceaccountrolemapping-" in d["metadata"]["name"]}
RD = next(d for d in docs if d.get("kind") == "RestDefinition"
          and d["metadata"]["name"].endswith("-serviceaccountrolemapping"))["spec"]["resource"]
NOT_FOUND = RD["observeApiRef"]["notFoundExpr"]["inline"]
UP_TO_DATE = RD["observeApiRef"]["upToDateExpr"]["inline"]
GET = next(v for v in RD["verbsDescription"] if v["action"] == "get")
FAILS = []


def check(desc, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + desc + ("" if cond or got is None else f"   (got: {got})"))
    if not cond:
        FAILS.append(desc)


def jq(prog, data):
    p = subprocess.run(["jq", "-c", prog], input=json.dumps(data), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"jq: {p.stderr}\n{prog}")
    return json.loads(p.stdout)


def tpl(s, item):
    m = re.fullmatch(r"\s*\$\{(.*)\}\s*", s, re.S)
    return jq(m.group(1), item) if m else s


TOKEN = None


def login():
    global TOKEN
    body = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli",
                                   "username": os.environ["KC_ADMIN"], "password": os.environ["KC_ADMIN_PASS"]}).encode()
    with urllib.request.urlopen(KC + "/realms/master/protocol/openid-connect/token", data=body) as r:
        TOKEN = json.load(r)["access_token"]


def http(method, path, payload=None):
    """-> (status, decoded-or-None, raw). Raises nothing."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(KC + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None), raw
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode()


CALLS = []


def run_restaction(spec, extras):
    """snowplow: stages in order; iterator fans out per item; merge like jsonHandlerCore."""
    d = dict(extras)
    for st in spec["api"]:
        items = jq(st["dependsOn"]["iterator"], d) if st.get("dependsOn", {}).get("iterator") else [d]
        for it in items:
            method = st.get("verb", "GET")
            path = tpl(st["path"], it)
            payload = tpl(st["payload"], it) if st.get("payload") else None
            code, val, raw = http(method, path, payload)
            CALLS.append((method, path, code))
            ok = 200 <= code < 300 and val is not None   # empty 2xx body = JSON stage error
            if not ok:
                if st.get("continueOnError"):
                    d.setdefault(st["errorKey"], []).append({"code": code, "body": raw[:120]})
                    continue
                return d, f"stage {st['name']} failed ({code})"   # chain truncated
            if st["name"] not in d:
                d[st["name"]] = val
            else:   # second+ call of the same stage: accumulate
                prev = d[st["name"]]
                d[st["name"]] = (prev if isinstance(prev, list) else [prev]) + (val if isinstance(val, list) else [val])
    return d, None


def extras_for(cr):
    return {"name": "sarm", "namespace": "kog", "realm": cr["realm"], "clientId": cr["clientId"],
            "roleClientId": cr["roleClientId"], "spec": cr}


def observe(cr):
    d, err = run_restaction(RA["observe"], extras_for(cr))
    return jq(RA["observe"]["filter"], d) if err is None else {"_error": err}


def reconcile(cr, passes=4):
    """rdc loop: until up to date or pass cap. Returns (status, actions)."""
    acts = []
    for _ in range(passes):
        st = observe(cr)
        ctx = {"spec": cr, "status": st}
        if jq(NOT_FOUND, ctx):
            acts.append("create"); run_restaction(RA["apply"], extras_for(cr)); continue
        if not jq(UP_TO_DATE, ctx):
            acts.append("update"); run_restaction(RA["apply"], extras_for(cr)); continue
        return st, acts
    return observe(cr), acts


def kc_held(uid, rid):
    return sorted(r["name"] for r in http("GET", f"/admin/realms/{REALM}/users/{uid}/role-mappings/clients/{rid}")[1])


def client_id(cid):
    return (http("GET", f"/admin/realms/{REALM}/clients?clientId={cid}")[1] or [{}])[0].get("id")


login()
http("DELETE", f"/admin/realms/{REALM}")
code, _, raw = http("POST", "/admin/realms", {"realm": REALM, "enabled": True})
check(f"fixture realm {REALM} created", code == 201, raw[:120])
CR = {"realm": REALM, "clientId": "identity-lifecycle", "roleClientId": "realm-management",
      "roles": ["manage-users", "view-users", "query-groups"]}
WANT = sorted(CR["roles"])

print("1. CR before its client exists")
CALLS.clear()
st, acts = reconcile(CR, passes=2)
check("observe -> {found:false}, every pass invokes create", st == {"found": False} and acts == ["create", "create"], (st, acts))
check("no mutating call reached Keycloak", all(m == "GET" for m, _, _ in CALLS), [c for c in CALLS if c[0] != "GET"])

print("2. client created (confidential, service account only) -> exact set converges")
code, _, raw = http("POST", f"/admin/realms/{REALM}/clients",
                    {"clientId": "identity-lifecycle", "publicClient": False, "serviceAccountsEnabled": True,
                     "standardFlowEnabled": False, "directAccessGrantsEnabled": False})
check("fixture client created", code == 201, raw[:120])
st, acts = reconcile(CR)
check("one update converges (found at once: adopt-then-update)", acts == ["update"] and st.get("roles") == WANT, (acts, st))
UID, RID = st.get("userId"), st.get("roleClientUuid")
check("Keycloak holds exactly the declared roles", kc_held(UID, RID) == WANT, kc_held(UID, RID))
check("status.roleClientUuid is realm-management's id", RID == client_id("realm-management"))

print("3. hand-made drift: add manage-realm, remove view-users")
roles = {r["name"]: r for r in http("GET", f"/admin/realms/{REALM}/clients/{RID}/roles")[1]}
http("POST", f"/admin/realms/{REALM}/users/{UID}/role-mappings/clients/{RID}", [{"id": roles["manage-realm"]["id"], "name": "manage-realm"}])
http("DELETE", f"/admin/realms/{REALM}/users/{UID}/role-mappings/clients/{RID}", [{"id": roles["view-users"]["id"], "name": "view-users"}])
check("drift is in Keycloak", kc_held(UID, RID) == sorted(["manage-users", "query-groups", "manage-realm"]), kc_held(UID, RID))
st, acts = reconcile(CR)
check("one update reverts both", acts == ["update"] and kc_held(UID, RID) == WANT, (acts, kc_held(UID, RID)))

print("4. spec change: drop query-groups")
CR2 = dict(CR, roles=["manage-users", "view-users"])
st, acts = reconcile(CR2)
check("one update converges to the new set", acts == ["update"] and kc_held(UID, RID) == ["manage-users", "view-users"], (acts, kc_held(UID, RID)))

print("5. unknown role name")
CR3 = dict(CR, roles=["manage-users", "view-users", "query-groups", "no-such-role"])
st, acts = reconcile(CR3, passes=3)
check("known roles granted, CR never up to date", kc_held(UID, RID) == WANT and acts == ["update"] * 3, (acts, kc_held(UID, RID)))
st, acts = reconcile(CR)   # back to the valid spec
check("valid spec converges again", acts == [] and st.get("roles") == WANT, (acts, st))

print("6. delete with the client present -> every held role removed, get verification = gone")
d, err = run_restaction(RA["delete"], extras_for(CR))
check("delete RESTAction ran", err is None, err)
check("Keycloak holds none of realm-management's roles", kc_held(UID, RID) == [], kc_held(UID, RID))
gpath = GET["path"].replace("{realm}", REALM).replace("{userId}", UID).replace("{roleClientUuid}", RID)
code, body, _ = http("GET", gpath)
check("get answers 200 [] and notFoundBody reads it as gone", code == 200 and jq(GET["notFoundBody"]["inline"], body) is True, (code, body))

print("7. delete after the client is gone -> no-op, get 404")
reconcile(CR)
http("DELETE", f"/admin/realms/{REALM}/clients/{client_id('identity-lifecycle')}")
CALLS.clear()
d, err = run_restaction(RA["delete"], extras_for(CR))
check("delete is a no-op (no DELETE call)", err is None and not any(m == "DELETE" for m, _, _ in CALLS), CALLS)
code, _, _ = http("GET", gpath)
check("get 404s (service-account user gone with its client)", code == 404, code)

http("DELETE", f"/admin/realms/{REALM}")
print()
if FAILS:
    print(f"LIVE VALIDATION FAILED: {len(FAILS)}")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL LIVE ASSERTIONS PASSED")
PYEOF
