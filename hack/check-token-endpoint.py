#!/usr/bin/env python3
"""CI gate: the ESO token endpoint follows keycloak.baseUrl unless set explicitly (0.8.1).

The admin calls go to keycloak.baseUrl and the token is minted at auth.externalSecret.tokenEndpoint.
Before 0.8.1 the endpoint was a separate hard-coded default, so pointing baseUrl elsewhere (another
namespace, a Keycloak served under /keycloak) silently left the token minted by a different, or no,
Keycloak. Asserts, rendering a stamped copy:
  1. defaults                     -> exactly the pre-0.8.1 default URL (existing installs unchanged)
  2. baseUrl with a path prefix   -> <baseUrl>/realms/master/protocol/openid-connect/token
  3. baseUrl with a trailing "/"  -> no double slash
  4. explicit tokenEndpoint       -> wins over the derivation
  5. self-test: a render whose url ignored baseUrl is detected by assertion 2
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path
import yaml

CHART = Path("helm/keycloak-config-kog")
OLD_DEFAULT = "http://keycloak-service.keycloak-system.svc.cluster.local:8080/realms/master/protocol/openid-connect/token"


def url(*args):
    work = Path(tempfile.mkdtemp(prefix="tokenep-"))
    try:
        dst = work / "c"
        shutil.copytree(CHART, dst)
        cy = dst / "Chart.yaml"
        cy.write_text(cy.read_text().replace("CHART_VERSION", "0.0.0-ci"))
        p = subprocess.run(["helm", "template", "t", str(dst), *args], capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit(f"::error::render failed: {p.stderr.strip()[:300]}")
        wh = [d for d in yaml.safe_load_all(p.stdout) if d and d.get("kind") == "Webhook"]
        return wh[0]["spec"]["url"] if wh else None
    finally:
        shutil.rmtree(work, ignore_errors=True)


errors = []
got = url()
if got != OLD_DEFAULT:
    errors.append(f"defaults must render the pre-0.8.1 token endpoint {OLD_DEFAULT}, got {got}")
want = "http://keycloak-service.krateo-system.svc.cluster.local:8080/keycloak/realms/master/protocol/openid-connect/token"
got = url("--set", "keycloak.baseUrl=http://keycloak-service.krateo-system.svc.cluster.local:8080/keycloak")
if got != want:
    errors.append(f"a baseUrl with a path prefix must carry it into the token endpoint: want {want}, got {got}")
if OLD_DEFAULT == want:
    errors.append("self-test: the prefix case is indistinguishable from the default")
got = url("--set", "keycloak.baseUrl=http://kc.example.test:8080/")
if got != "http://kc.example.test:8080/realms/master/protocol/openid-connect/token":
    errors.append(f"a trailing slash in baseUrl must not double: got {got}")
got = url("--set", "keycloak.baseUrl=http://a.example.test", "--set", "auth.externalSecret.tokenEndpoint=https://b.example.test/token")
if got != "https://b.example.test/token":
    errors.append(f"an explicit tokenEndpoint must win: got {got}")
for e in errors:
    print(f"::error::{e}")
if errors:
    sys.exit(1)
print("Checked the token endpoint: pre-0.8.1 default unchanged, derived from baseUrl (prefix kept, no double slash), explicit value wins.")
