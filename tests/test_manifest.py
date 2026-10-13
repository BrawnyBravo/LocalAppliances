import json
from pathlib import Path

from smartthings_local.protocol import _dtls_psk, auth, dtls_session

_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST = json.loads((_ROOT / "custom_components/localthings/manifest.json").read_text())


def test_debug_logging_covers_the_protocol_library():
    """Home Assistant's "Enable debug logging" raises only the integration's
    package and the manifest's `loggers`, and the DTLS handshake and auth
    traces are logged from smartthings_local."""
    loggers = _MANIFEST["loggers"]
    for module in (_dtls_psk, auth, dtls_session):
        name = module.logger.name
        assert any(name == root or name.startswith(f"{root}.") for root in loggers), name
