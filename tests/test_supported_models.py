"""The generated supported-models page must build and must stay free of private data."""

import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "supported_models.py"

MAC = re.compile(r"(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _build():
    module = runpy.run_path(str(SCRIPT))
    return module["build"]()


def test_generation_works():
    text, rows = _build()
    assert text.startswith("# Supported models")
    assert rows > 0
    assert "not affiliated with samsung" in text.lower()


def test_output_has_no_private_patterns():
    text, _ = _build()
    for pattern in (MAC, UUID, IPV4):
        assert not pattern.search(text), pattern.pattern
    assert "@" not in text
    assert "serial" not in text.lower()


def test_committed_page_is_current():
    text, _ = _build()
    assert (ROOT / "docs" / "supported-models.md").read_text(encoding="utf-8") == text
