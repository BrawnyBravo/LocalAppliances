"""Generate docs/supported-models.md from the captures in tests/fixtures.

Run from the repo root:  python -I scripts/supported_models.py
Check mode (for CI):     python -I scripts/supported_models.py --check

Privacy: only appliance type, model code / board id, transport, entity count
and capture count are published. Everything else in a capture is ignored.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = FIXTURES / "golden"
OUT = ROOT / "docs" / "supported-models.md"

# Longest prefix wins.
TYPES = {
    "air_dresser": "Air dresser",
    "air_monitor": "Air monitor",
    "air_purifier": "Air purifier",
    "airconditioner": "Air conditioner",
    "cooktop": "Cooktop",
    "induction_cooktop": "Cooktop",
    "dehumidifier": "Dehumidifier",
    "dishwasher": "Dishwasher",
    "dryer": "Dryer",
    "ehs": "Heat pump (EHS)",
    "microfiber": "Microfiber",
    "microwave": "Microwave",
    "oven": "Oven",
    "qooker": "Microwave",
    "range": "Range",
    "range_hood": "Range hood",
    "refrigerator": "Refrigerator",
    "soundbar": "Soundbar",
    "vacuum_station": "Vacuum station",
    "washer": "Washer",
    "washer_dryer_combo": "Washer-dryer",
    "water_purifier": "Water purifier",
}

BOARD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{1,63}$")
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-]{3,31}$")
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def appliance_type(stem):
    best = None
    for prefix in TYPES:
        if (stem == prefix or stem.startswith(prefix + "_")) and (
            best is None or len(prefix) > len(best)
        ):
            best = prefix
    return TYPES[best] if best else stem.split("_")[0].capitalize()


def find_key(node, key):
    """Yield every value stored under `key` anywhere in a JSON tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from find_key(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from find_key(v, key)


def first_str(node, *keys):
    for key in keys:
        for v in find_key(node, key):
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def clean_board(raw):
    if not raw:
        return None
    raw = raw.split("|")[0].split("/")[0].strip()
    if raw.upper().startswith("TEST") or "REDACT" in raw.upper():
        return None
    if not BOARD_RE.match(raw) or MAC_RE.match(raw) or UUID_RE.match(raw):
        return None
    return raw


def clean_codes(raw):
    """'M(DV80H20BBY),W(None)' -> ['DV80H20BBY']; a bare code passes through."""
    if not raw:
        return []
    found = re.findall(r"[MW]\(([^)]*)\)", raw) or [raw]
    codes = []
    for c in found:
        c = c.strip()
        if c and c.lower() != "none" and CODE_RE.match(c) and c not in codes:
            codes.append(c)
    return codes


def entity_count(stem):
    name = stem[: -len("_device")] if stem.endswith("_device") else stem
    path = GOLDEN / (name + ".json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("discovery_unique_ids", "state_keys"):
        if isinstance(data.get(key), list):
            return len(data[key])
    return None


def read_capture(path):
    stem = path.stem
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    legacy = "bodies" in data or "/devices" in data or "_8888" in stem
    if not legacy and "device0" not in data:
        return None  # helper data, not a device capture
    # Only the identity block is read: the information resource's own
    # top-level fields (nested "description" fields are alarms, sensors etc.).
    info = {}
    for entry in data.get("device0") or []:
        if isinstance(entry, dict) and entry.get("href") == "/information/vs/0":
            info = entry.get("rep") or {}
    for key in ("/devices/0/information",):
        if isinstance(data.get(key), dict):
            info = data[key]
    for body in find_key(data, "Information"):
        if isinstance(body, dict) and not info:
            info = body
    if isinstance(info.get("Information"), dict):
        info = info["Information"]
    # Board id: modelNum / modelID start with it; description is the fallback.
    board = (
        clean_board(info.get("x.com.samsung.da.modelNum"))
        or clean_board(info.get("modelID"))
        or clean_board(info.get("x.com.samsung.da.description"))
        or clean_board(info.get("description"))
    )
    codes = clean_codes(first_str(data, "x.com.samsung.da.modelCode"))
    transport = "Legacy HTTP (port 8888)" if legacy else "CoAP/DTLS"
    return {
        "type": appliance_type(stem),
        "board": board or "unknown",
        "model": ", ".join(codes) if codes else "board only",
        "transport": transport,
        "entities": entity_count(stem),
    }


def build():
    rows = Counter()
    for path in sorted(FIXTURES.glob("*.json")):
        rec = read_capture(path)
        if rec:
            rows[(rec["type"], rec["board"], rec["model"], rec["transport"], rec["entities"])] += 1
    lines = [
        "# Supported models",
        "",
        "Generated from the captures in tests/fixtures by scripts/supported_models.py; a model "
        "listed here has been seen by the integration, it is not a promise every feature works. "
        "Not affiliated with Samsung or SmartThings.",
        "",
        "Do not see your model? Open an issue with your diagnostics attached and we can add a "
        "capture. See [CONTRIBUTING.md](../CONTRIBUTING.md) for how.",
        "",
        "Model code is shown only when the appliance reported one; otherwise the row says "
        '"board only". Board "unknown" means the capture carries no identity block. '
        "Entities is the size of the capture's reference list of entities or state values "
        '("n/a" when it has none).',
    ]
    by_type = {}
    for key, count in rows.items():
        by_type.setdefault(key[0], []).append((key, count))
    for t in sorted(by_type):
        lines += [
            "",
            f"## {t}",
            "",
            "| Board | Model code | Transport | Entities | Captures |",
            "| --- | --- | --- | --- | --- |",
        ]
        for (_, board, model, transport, ents), count in sorted(
            by_type[t], key=lambda x: (x[0][1], x[0][2], x[0][3], str(x[0][4]))
        ):
            shown = "n/a" if ents is None else ents
            lines.append(f"| {board} | {model} | {transport} | {shown} | {count} |")
    return "\n".join(lines) + "\n", sum(len(v) for v in by_type.values())


def main(argv):
    text, _ = build()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
        if current != text:
            print("docs/supported-models.md is out of date; run scripts/supported_models.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
