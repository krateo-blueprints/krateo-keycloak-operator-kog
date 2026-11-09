#!/usr/bin/env python3
"""Offline chart checks that catch two classes of silent defect. Exit 1 on any finding.

1. Chart URLs. Every URL in Chart.yaml (icon, home, sources) must avoid the renamed org
   `krateoplatformops`: GitHub's rename redirect keeps it answering 200, so a stale link never
   looks broken until the redirect goes. The icon must also live under a Krateo-controlled path,
   so a third-party site reorganising can't break the Marketplace card. Self-hosted icons
   must point at a committed file. No network calls, so the check can't fail for reasons
   unrelated to the chart.

2. Status fields. Every `additionalStatusFields` path a RestDefinition declares must exist in
   the response schema of its `get` verb (falling back to `findby`). oasgen types status fields
   from that schema, so a path missing from it silently stays empty and nothing reports it.
   A stage that can't be resolved (no verb, no ConfigMap, no JSON schema, missing $ref) is
   reported as its own error, never as a missing field. Checking zero declarations is an error,
   so a broken walk can't pass forever.

Both checks run their self-tests through the SAME functions as the real run, including cases
they must refuse, so a check that has silently stopped refusing anything fails here first.

Usage: validate-chart.py <chart-dir> <rendered-manifests.yaml> <repo-root>
"""
import os
import sys

import yaml

DEAD_ORG = "krateoplatformops"
ICON_OK_PREFIXES = (
    "https://raw.githubusercontent.com/krateo-platformops/",
    "https://raw.githubusercontent.com/krateo-blueprints/",
)
SELF_HOSTED_PREFIX = "https://raw.githubusercontent.com/krateo-blueprints/krateo-keycloak-operator-kog/main/"


# --------------------------------------------------------------------------- chart URLs

def judge_url(field, url, repo_root):
    """Return a complaint for one Chart.yaml URL, or None if it is acceptable."""
    if not url:
        return f"{field}: empty" if field == "icon" else None
    if DEAD_ORG in url:
        return (f"{field} names the renamed org {DEAD_ORG!r}, which still answers through "
                f"GitHub's redirect and so would fail silently: {url}")
    if field != "icon":
        return None
    if not url.startswith("https://"):
        return f"icon is not https: {url}"
    if not url.startswith(ICON_OK_PREFIXES):
        return f"icon is not under a Krateo-controlled path, so it can rot without warning: {url}"
    if url.startswith(SELF_HOSTED_PREFIX):
        rel = url[len(SELF_HOSTED_PREFIX):]
        if not os.path.isfile(os.path.join(repo_root, rel)):
            return f"icon is self-hosted but {rel!r} is not committed in this repo: {url}"
    return None


def check_chart_urls(chart, repo_root):
    errors = []
    urls = [("icon", chart.get("icon", "")), ("home", chart.get("home", ""))]
    urls += [("sources", s) for s in (chart.get("sources") or [])]
    for field, url in urls:
        complaint = judge_url(field, url, repo_root)
        if complaint:
            errors.append(complaint)
    return errors, len(urls)


def selftest_chart_urls(repo_root):
    cases = [
        ("icon", "https://raw.githubusercontent.com/krateoplatformops/krateo/main/docs/media/logo.svg", True),
        ("sources", "https://github.com/krateoplatformops/oasgen-provider", True),
        ("home", "https://github.com/krateoplatformops/whatever", True),
        ("icon", "http://raw.githubusercontent.com/krateo-platformops/.github/main/brand/logo.svg", True),
        ("icon", "https://www.openstack.org/themes/openstack/images/logo.png", True),
        ("icon", "", True),
        ("icon", SELF_HOSTED_PREFIX + "docs/images/not-committed-icon.svg", True),
        ("icon", "https://raw.githubusercontent.com/krateo-platformops/.github/main/brand/logo.svg", False),
        ("sources", "https://github.com/krateo-blueprints/krateo-keycloak-operator-kog", False),
        ("home", "https://www.keycloak.org/", False),
    ]
    errors = []
    for field, url, must_refuse in cases:
        got = judge_url(field, url, repo_root)
        if must_refuse and got is None:
            errors.append(f"self-test: the URL check ACCEPTS {field}={url!r}, which it must refuse, "
                          f"so its silence means nothing")
        if not must_refuse and got is not None:
            errors.append(f"self-test: the URL check refuses a legitimate {field}={url!r}: {got}")
    return errors


# --------------------------------------------------------------------------- status fields

def resolve_ref(schema, oas, depth=0):
    """Follow $ref and merge allOf one level. Return (schema, error)."""
    if depth > 20:
        return None, "$ref chain too deep"
    if not isinstance(schema, dict):
        return None, "schema is not an object"
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return None, f"unsupported $ref {ref!r}"
        node = oas
        for part in ref[2:].split("/"):
            if not isinstance(node, dict) or part not in node:
                return None, f"$ref target missing: {ref}"
            node = node[part]
        return resolve_ref(node, oas, depth + 1)
    if "allOf" in schema:
        merged = {"type": "object", "properties": {}}
        for sub in schema["allOf"]:
            s, err = resolve_ref(sub, oas, depth + 1)
            if err:
                return None, err
            merged["properties"].update(s.get("properties") or {})
        merged["properties"].update(schema.get("properties") or {})
        return merged, None
    return schema, None


def response_schema(oas, method, path):
    """Return (schema, error) for the JSON success response of one operation."""
    op = ((oas.get("paths") or {}).get(path) or {}).get(method.lower())
    if not op:
        return None, f"operation {method} {path} not found in the OAS document"
    responses = op.get("responses") or {}
    for code in ("200", "201", "default"):
        resp = responses.get(code)
        if resp is None and code != "default":
            resp = responses.get(int(code))  # YAML may load an unquoted 200 as an int
        if not resp:
            continue
        resp, err = resolve_ref(resp, oas) if "$ref" in resp else (resp, None)
        if err:
            return None, err
        schema = ((resp.get("content") or {}).get("application/json") or {}).get("schema")
        if schema is not None:
            return resolve_ref(schema, oas)
    return None, f"no application/json schema on the 200/201/default response of {method} {path}"


def walk(schema, dotted, oas):
    """Return None if the dotted path exists in the schema, else a reason string."""
    node = schema
    for seg in dotted.split("."):
        node, err = resolve_ref(node, oas)
        if err:
            return err
        props = node.get("properties") or {}
        if seg not in props:
            return f"segment {seg!r} is not a property"
        node = props[seg]
    return None


def check_status_fields(docs):
    configmaps = {(d["metadata"].get("namespace", ""), d["metadata"]["name"]): d.get("data") or {}
                  for d in docs if d.get("kind") == "ConfigMap"}
    errors, checked = [], 0
    for d in docs:
        if d.get("kind") != "RestDefinition":
            continue
        name = d["metadata"]["name"]
        res = d["spec"]["resource"]
        fields = res.get("additionalStatusFields") or []
        if not fields:
            continue
        oas_path = d["spec"].get("oasPath", "")
        if not oas_path.startswith("configmap://"):
            errors.append(f"{name}: oasPath {oas_path!r} is not a configmap:// path, so it could not be checked")
            continue
        try:
            _ns, cm_name, key = oas_path[len("configmap://"):].split("/", 2)
        except ValueError:
            errors.append(f"{name}: oasPath {oas_path!r} did not parse as configmap://ns/name/key")
            continue
        data = next((v for (n, c), v in configmaps.items() if c == cm_name), None)
        if data is None or key not in data:
            errors.append(f"{name}: oasPath {oas_path!r} did not resolve to a rendered ConfigMap key")
            continue
        oas = yaml.safe_load(data[key])
        verbs = {v["action"]: v for v in res.get("verbsDescription") or []}
        verb = verbs.get("get") or verbs.get("findby")
        if not verb:
            errors.append(f"{name}: no get or findby verb, so status fields could not be checked")
            continue
        schema, err = response_schema(oas, verb["method"], verb["path"])
        if err:
            errors.append(f"{name}: {err}")
            continue
        if verb["action"] == "findby" and schema.get("type") == "array":
            schema, err = resolve_ref(schema.get("items") or {}, oas)
            if err:
                errors.append(f"{name}: findby items: {err}")
                continue
        for field in fields:
            checked += 1
            reason = walk(schema, field, oas)
            if reason:
                errors.append(f"{name}: additionalStatusFields {field!r} is not in the "
                              f"{verb['action']} response schema ({reason}), so it would silently stay empty")
    return errors, checked


def selftest_status_fields():
    oas = {"paths": {"/x/{id}": {"get": {"responses": {"200": {"content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/X"}}}}}}}},
        "components": {"schemas": {"X": {"type": "object", "properties": {"id": {"type": "string"}}}}}}
    def docs(fields):
        return [
            {"kind": "ConfigMap", "metadata": {"name": "cm", "namespace": "ns"},
             "data": {"x.yaml": yaml.safe_dump(oas)}},
            {"kind": "RestDefinition", "metadata": {"name": "st"},
             "spec": {"oasPath": "configmap://ns/cm/x.yaml",
                      "resource": {"additionalStatusFields": fields,
                                   "verbsDescription": [{"action": "get", "method": "GET", "path": "/x/{id}"}]}}},
        ]
    errors = []
    e, n = check_status_fields(docs(["id"]))
    if e or n != 1:
        errors.append(f"self-test: a declared field present in the schema was not accepted (errors={e}, checked={n})")
    e, n = check_status_fields(docs(["doesNotExist"]))
    if not e:
        errors.append("self-test: the status-field check ACCEPTS a field absent from the schema, so its silence means nothing")
    return errors


# --------------------------------------------------------------------------- main

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    chart_dir, rendered, repo_root = sys.argv[1:]
    errors = selftest_chart_urls(repo_root) + selftest_status_fields()
    with open(os.path.join(chart_dir, "Chart.yaml")) as f:
        chart = yaml.safe_load(f)
    e, n_urls = check_chart_urls(chart, repo_root)
    errors += e
    with open(rendered) as f:
        docs = [d for d in yaml.safe_load_all(f) if isinstance(d, dict)]
    e, n_fields = check_status_fields(docs)
    errors += e
    if n_fields == 0:
        errors.append("checked 0 additionalStatusFields declarations: the walk is broken or found no RestDefinitions")
    print(f"Checked {n_urls} Chart.yaml URL(s) and {n_fields} additionalStatusFields declaration(s).")
    for err in errors:
        print(f"::error::{err}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
