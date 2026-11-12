#!/usr/bin/env python3
"""CI gate: every key values.yaml sets is declared in values.schema.json.

WHY. Krateo's core-provider generates the Composition CRD from values.schema.json, and an installer
that embeds this chart mirrors it. A key that values.yaml sets but the schema does not declare cannot
be set through either: the API server prunes it silently and the chart default always wins. Measured:
restDefinitions.user was in values.yaml and missing from the schema from 0.6.0 to 0.7.1.

WHAT. Walk values.yaml; wherever the schema node at the same path lists `properties` and does not
allow additionalProperties, every key must be one of them. Lists and free-form maps are not walked.
SELF-TEST. A mutant values.yaml with an undeclared key must fail.
"""
import json, sys, copy
from pathlib import Path
import yaml

CHARTS = [p.parent for p in Path("helm").glob("*/values.schema.json") if (p.parent / "values.yaml").exists()]


def undeclared(values, schema, path=""):
    out = []
    if not isinstance(values, dict) or not isinstance(schema, dict):
        return out
    props = schema.get("properties")
    if props is None:
        return out
    for k, v in values.items():
        p = f"{path}.{k}" if path else k
        if k not in props:
            if schema.get("additionalProperties") in (None, False):
                out.append(p)
            continue
        out += undeclared(v, props[k], p)
    return out


errors = []
for c in CHARTS:
    schema = json.loads((c / "values.schema.json").read_text())
    values = yaml.safe_load((c / "values.yaml").read_text()) or {}
    mutant = copy.deepcopy(values); mutant["selfTestUndeclaredKey"] = 1
    if "selfTestUndeclaredKey" not in undeclared(mutant, schema):
        sys.exit("::error::self-test: an undeclared key passed; the gate is broken")
    errors += [f"{c}/values.yaml sets `{p}`, which values.schema.json does not declare" for p in undeclared(values, schema)]
for e in errors:
    print(f"::error::{e}")
if errors:
    sys.exit(1)
print(f"Checked {len(CHARTS)} chart(s): every values.yaml key is declared in values.schema.json.")
