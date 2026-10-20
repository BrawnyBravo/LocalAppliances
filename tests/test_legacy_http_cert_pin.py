"""Trust-on-first-use pinning of the 8888 appliance's TLS certificate
(review finding M3).

The appliance's certificate cannot be validated against any chain, and
every request carries the bearer device token. Without a pin, anything that
took over the appliance's address would receive the token on the next poll.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import (
    CONF_DEVICE_TOKEN,
    CONF_HOST,
    CONF_LEAF_CERT_PEM,
    CONF_LEAF_KEY_PEM,
    CONF_LEGACY_CERT_SHA256,
    CONF_LEGACY_FAMILY,
    CONF_PORT,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_LEGACY_HTTP,
)
from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.credentials import ApplianceCertificateMismatch
from custom_components.localthings.legacy_http_transport import LegacyHttpTransport
from custom_components.localthings.transport import AuthRejected

CERT_A = b"appliance-certificate-A"
CERT_B = b"someone-else-certificate-B"
PIN_A = hashlib.sha256(CERT_A).hexdigest()


class _Sock:
    def __init__(self, der: bytes | None) -> None:
        self._der = der

    def getpeercert(self, binary_form: bool = False):
        assert binary_form
        return self._der


class _Conn:
    peer: ClassVar[bytes | None] = CERT_A
    status: ClassVar[int] = 200
    sent: ClassVar[list[dict]] = []

    def __init__(self, host, port, context=None, timeout=None) -> None:
        self.sock = None

    def connect(self) -> None:
        self.sock = _Sock(_Conn.peer)

    def request(self, method, path, body=None, headers=None) -> None:
        _Conn.sent.append(dict(headers or {}))

    def getresponse(self):
        status = _Conn.status

        class _Response:
            def __init__(self) -> None:
                self.status = status

            def read(self) -> bytes:
                return json.dumps({"Device": {}}).encode()

        return _Response()

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_https(monkeypatch):
    _Conn.peer, _Conn.status, _Conn.sent = CERT_A, 200, []
    monkeypatch.setattr(
        "custom_components.localthings.legacy_http_transport.http.client.HTTPSConnection", _Conn
    )
    monkeypatch.setattr(
        "custom_components.localthings.legacy_http_transport.client_context",
        lambda cert_pem, key_pem: object(),
    )
    monkeypatch.setattr("custom_components.localthings.legacy_http_transport._STATE", {})


def _transport(pin: str | None = None) -> LegacyHttpTransport:
    t = LegacyHttpTransport(
        "192.0.2.10", 8888, cert_pem="C", key_pem="K", token="tok123456", cert_fingerprint=pin
    )
    t.connect()
    return t


def test_unpinned_transport_learns_the_first_certificate() -> None:
    t = _transport()
    t._request("GET", "/devices/0", timeout=5)
    assert t.learned_cert_fingerprint == PIN_A


def test_a_refused_token_teaches_nothing() -> None:
    _Conn.status = 401
    t = _transport()
    with pytest.raises(AuthRejected):
        t._request("GET", "/devices/0", timeout=5)
    assert t.learned_cert_fingerprint is None


def test_pinned_transport_accepts_the_same_certificate() -> None:
    t = _transport(PIN_A)
    status, _ = t._request("GET", "/devices/0", timeout=5)
    assert status == 200
    assert t.learned_cert_fingerprint is None  # nothing new to record


@pytest.mark.parametrize("peer", [CERT_B, None])
def test_a_different_certificate_never_receives_the_token(peer) -> None:
    _Conn.peer = peer
    t = _transport(PIN_A)
    with pytest.raises(ApplianceCertificateMismatch):
        t._request("GET", "/devices/0", timeout=5)
    assert _Conn.sent == []


def _legacy_entry(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 8888,
            CONF_LEAF_CERT_PEM: "C",
            CONF_LEAF_KEY_PEM: "K",
            CONF_TRANSPORT: TRANSPORT_LEGACY_HTTP,
            CONF_LEGACY_FAMILY: "TP6X_WASHER",
            CONF_DEVICE_TOKEN: "tok123456",
            **extra,
        },
        unique_id="localthings_PIN-TEST",
        version=4,
    )
    entry.add_to_hass(hass)
    return entry


async def test_an_existing_entry_learns_its_pin_on_first_success(hass: HomeAssistant) -> None:
    """Entries made before pinning existed pick it up without any user
    action -- not a breaking change."""
    entry = _legacy_entry(hass)
    coord = LocalThingsCoordinator(hass, entry)
    session = _transport()
    session._request("GET", "/devices/0", timeout=5)
    coord._session = session

    coord._mark_device_answered()
    assert entry.data[CONF_LEGACY_CERT_SHA256] == PIN_A


async def test_a_stored_pin_is_not_overwritten(hass: HomeAssistant) -> None:
    entry = _legacy_entry(hass, **{CONF_LEGACY_CERT_SHA256: "ef" * 32})
    coord = LocalThingsCoordinator(hass, entry)
    session = _transport()
    session._request("GET", "/devices/0", timeout=5)
    coord._session = session

    coord._mark_device_answered()
    assert entry.data[CONF_LEGACY_CERT_SHA256] == "ef" * 32


async def test_a_certificate_mismatch_raises_its_own_repair(hass: HomeAssistant) -> None:
    entry = _legacy_entry(hass, **{CONF_LEGACY_CERT_SHA256: PIN_A})
    coord = LocalThingsCoordinator(hass, entry)
    coord.async_request_refresh = AsyncMock()
    _Conn.peer = CERT_B
    coord._session = _transport(PIN_A)

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"device_identity_mismatch_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "appliance_certificate_changed"
    assert _Conn.sent == []


def test_handshake_only_fingerprint_sends_nothing() -> None:
    from custom_components.localthings.legacy_http_transport import fetch_peer_fingerprint

    assert fetch_peer_fingerprint("192.0.2.10", 8888, "C", "K") == PIN_A
    assert _Conn.sent == []


def test_a_pinned_probe_refuses_a_different_certificate_before_any_request() -> None:
    """What reauth and Reconfigure rely on: the new or existing token never
    reaches a peer that does not hold the pinned certificate."""
    from custom_components.localthings.config_flow import _probe_legacy

    _Conn.peer = CERT_B
    with pytest.raises(ApplianceCertificateMismatch):
        _probe_legacy("192.0.2.10", "C", "K", "new-token", PIN_A)
    assert _Conn.sent == []
