"""The 8888 transport's per-address memory (review finding L5): dropped when
its entry is deleted, and safe to read for diagnostics while a poll thread
adds to it."""

from __future__ import annotations

import sys
import threading

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings import async_remove_entry
from custom_components.localthings import legacy_http_transport as lht
from custom_components.localthings.const import (
    CONF_DEVICE_TOKEN,
    CONF_HOST,
    CONF_LEAF_CERT_PEM,
    CONF_LEAF_KEY_PEM,
    CONF_PORT,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_LEGACY_HTTP,
)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(lht, "_STATE", {})


def test_forget_drops_only_that_address() -> None:
    lht._STATE[("192.0.2.10", 8888, 0)] = lht._ApplianceState()
    lht._STATE[("192.0.2.10", 8888, 1)] = lht._ApplianceState()
    lht._STATE[("192.0.2.11", 8888, 0)] = lht._ApplianceState()

    lht.forget("192.0.2.10", 8888)

    assert list(lht._STATE) == [("192.0.2.11", 8888, 0)]


async def test_deleting_a_legacy_entry_forgets_its_held_values(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 8888,
            CONF_LEAF_CERT_PEM: "C",
            CONF_LEAF_KEY_PEM: "K",
            CONF_TRANSPORT: TRANSPORT_LEGACY_HTTP,
            CONF_DEVICE_TOKEN: "tok123456",
        },
    )
    entry.add_to_hass(hass)
    lht._STATE[("192.0.2.10", 8888, 0)] = lht._ApplianceState(last_bodies={"Device": {}})

    await async_remove_entry(hass, entry)

    assert lht._STATE == {}


def test_diagnostics_survives_a_concurrent_new_index(monkeypatch) -> None:
    """An executor thread adding an index while diagnostics iterates used to
    be able to raise "dictionary changed size during iteration"."""
    monkeypatch.setattr(lht, "client_context", lambda cert_pem, key_pem: object())
    transport = lht.LegacyHttpTransport(
        "192.0.2.10", 8888, cert_pem="C", key_pem="K", token="tok123456", family="TP6X_WASHER"
    )
    for index in range(200):
        lht._STATE[("192.0.2.10", 8888, index)] = lht._ApplianceState(
            last_bodies={"Device": {}}
        )

    stop = threading.Event()

    def _add() -> None:
        # Add and drop one index over and over: the dict keeps changing size
        # without growing, so every diagnostics call stays cheap.
        key = ("192.0.2.20", 8888, 1000)
        while not stop.is_set():
            lht._STATE.setdefault(key, lht._ApplianceState())
            lht._STATE.pop(key, None)

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    writer = threading.Thread(target=_add)
    writer.start()
    try:
        for _ in range(300):
            transport.diagnostics()
    finally:
        stop.set()
        writer.join()
        sys.setswitchinterval(previous)
