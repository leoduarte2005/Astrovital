#!/usr/bin/env python3
"""Offline JSON Schema (draft 2020-12) contract validator for EdgeSpace."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"
ENUMS_DIR = CONTRACTS_DIR / "enums"
SCHEMA_DIR = CONTRACTS_DIR / "jsonschema"
FIXTURES_DIR = CONTRACTS_DIR / "fixtures"

CHANNELS = ("udp", "ipc", "ws", "rest")


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _build_registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for base in (ENUMS_DIR, SCHEMA_DIR):
        for p in sorted(base.rglob("*.json")):
            doc = _load_json(p)
            uri = p.resolve().as_uri()
            resources.append((uri, DRAFT202012.create_resource(doc)))
    return Registry().with_resources(resources)


GO_ENUMS_FILE = ROOT / "central" / "internal" / "contracts" / "enums.go"
PY_PROTOCOL_FILE = ROOT / "edge-ai" / "src" / "edgespace_ai" / "ipc" / "protocol.py"

# Go type / Python class -> contracts/enums/<name>.json
GO_ENUM_TYPES = {
    "MissionMode": "mission_mode",
    "Subsystem": "subsystem",
    "Severity": "severity",
    "Escalation": "escalation",
    "UDPMsgType": "udp_msg_type",
    "IPCMsgType": "ipc_msg_type",
    "WSMsgType": "ws_msg_type",
    "Peripheral": "peripheral",
    "NodeState": "node_state",
}
PY_ENUM_CLASSES = {
    "MissionMode": "mission_mode",
    "Peripheral": "peripheral",
    "Escalation": "escalation",
    "IPCMsgType": "ipc_msg_type",
}


def _go_enum_values() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not GO_ENUMS_FILE.is_file():
        return out
    text = GO_ENUMS_FILE.read_text(encoding="utf-8")
    pat = re.compile(r"^\s*\w+\s+(\w+)\s*=\s*\"([A-Z0-9_]+)\"", re.MULTILINE)
    for go_type, value in pat.findall(text):
        name = GO_ENUM_TYPES.get(go_type)
        if name:
            out.setdefault(name, set()).add(value)
    return out


def _py_enum_values() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not PY_PROTOCOL_FILE.is_file():
        return out
    text = PY_PROTOCOL_FILE.read_text(encoding="utf-8")
    for cls, name in PY_ENUM_CLASSES.items():
        m = re.search(rf"^class {cls}\(str, Enum\):\n((?:[ \t]+.*\n)+)", text, re.MULTILINE)
        if not m:
            continue
        out[name] = set(re.findall(r"=\s*\"([A-Z0-9_]+)\"", m.group(1)))
    return out


def _check_enum_parity(enum_values: dict[str, set[str]], errors: list[str]) -> None:
    for lang, mirror in (("Go", _go_enum_values()), ("Python", _py_enum_values())):
        for name, values in mirror.items():
            expected = enum_values.get(name)
            if expected is None:
                errors.append(f"{lang} enum {name} has no contracts/enums/{name}.json")
                continue
            if values != expected:
                errors.append(
                    f"{lang} enum {name} diverges from contracts: "
                    f"missing={sorted(expected - values)} extra={sorted(values - expected)}"
                )


def main() -> int:
    errors: list[str] = []
    enum_values: dict[str, set[str]] = {}

    for enum_path in sorted(ENUMS_DIR.glob("*.json")):
        doc = _load_json(enum_path)
        Draft202012Validator.check_schema(doc)
        values = doc.get("enum")
        if not isinstance(values, list) or not values:
            errors.append(f"enum missing non-empty list: {enum_path}")
            continue
        enum_values[enum_path.stem] = set(values)

    _check_enum_parity(enum_values, errors)

    registry = _build_registry()
    schemas: dict[tuple[str, str], Path] = {}

    for defs_path in sorted(SCHEMA_DIR.glob("*.json")):
        Draft202012Validator.check_schema(_load_json(defs_path))

    for ch in CHANNELS:
        ch_dir = SCHEMA_DIR / ch
        if not ch_dir.is_dir():
            errors.append(f"missing schema channel dir: {ch_dir}")
            continue
        for sp in sorted(ch_dir.glob("*.json")):
            doc = _load_json(sp)
            Draft202012Validator.check_schema(doc)
            if sp.stem != "envelope":
                schemas[(ch, sp.stem)] = sp

    coverage: dict[tuple[str, str], dict[str, int]] = {
        k: {"valid": 0, "invalid": 0} for k in schemas
    }

    total_fixtures = 0
    for ch in CHANNELS:
        fx_dir = FIXTURES_DIR / ch
        if not fx_dir.is_dir():
            errors.append(f"missing fixtures channel dir: {fx_dir}")
            continue
        for fp in sorted(fx_dir.glob("*.json")):
            parts = fp.stem.split(".")
            if len(parts) < 3 or parts[1] not in ("valid", "invalid"):
                errors.append(f"invalid fixture filename (want <type>.(valid|invalid).<case>.json): {fp}")
                continue
            msg_type, expectation = parts[0], parts[1]
            key = (ch, msg_type)
            if key not in schemas:
                errors.append(f"no schema for fixture {fp} (expected {ch}/{msg_type}.json)")
                continue

            schema_path = schemas[key]
            schema_doc = _load_json(schema_path)
            if "$id" not in schema_doc:
                schema_doc["$id"] = schema_path.resolve().as_uri()
            validator = Draft202012Validator(schema_doc, registry=registry)

            instance = _load_json(fp)
            errs = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
            total_fixtures += 1
            coverage[key][expectation] += 1

            if expectation == "valid" and errs:
                first = errs[0]
                errors.append(f"FAIL valid fixture {fp.relative_to(ROOT)}: {first.message} at {list(first.path)}")
            elif expectation == "invalid" and not errs:
                errors.append(f"FAIL invalid fixture unexpectedly passed {fp.relative_to(ROOT)}")

    for key, counts in sorted(coverage.items()):
        if counts["valid"] == 0:
            errors.append(f"missing .valid. fixture for {key[0]}/{key[1]}")
        if counts["invalid"] == 0:
            errors.append(f"missing .invalid. fixture for {key[0]}/{key[1]}")

    if errors:
        for e in errors:
            print(f"[contracts-validate] ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"[contracts-validate] OK: {len(schemas)} schemas, "
        f"{total_fixtures} fixtures verified (valid + invalid)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
