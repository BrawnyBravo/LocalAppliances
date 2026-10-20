"""Closing the setup dialog ends a running 8888 token exchange and frees its
callback port right away (review finding L6), instead of holding port 8889
until the exchange's 90 s timeout -- which made an immediate retry fail with
callback_port_in_use."""

from __future__ import annotations

import asyncio
import threading
import time

from homeassistant.core import HomeAssistant

from custom_components.localthings import legacy_http_token
from custom_components.localthings.config_flow import LocalThingsConfigFlow


def test_a_stop_ends_the_exchange_and_releases_the_listener(monkeypatch) -> None:
    stop = threading.Event()
    stopped: list[bool] = []

    class _Listener:
        token = None
        handshake_failed = False

        def __init__(self, cert, key, peer) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            stopped.append(True)

    requests: list[str] = []

    def _request(host, port, address, context):
        requests.append(host)
        stop.set()  # the dialog is closed while waiting for the callback
        return 200

    monkeypatch.setattr(legacy_http_token, "TokenListener", _Listener)
    monkeypatch.setattr(legacy_http_token, "client_context", lambda cert, key: object())
    monkeypatch.setattr(legacy_http_token, "request_token", _request)
    monkeypatch.setattr(legacy_http_token.socket, "gethostbyname", lambda host: host)

    started = time.monotonic()
    token = legacy_http_token.obtain_device_token(
        "192.0.2.10", 8888, "C", "K", listen_address="192.0.2.2", stop=stop
    )

    assert token is None
    assert requests == ["192.0.2.10"]
    assert stopped == [True]
    assert time.monotonic() - started < 5


async def test_closing_the_flow_stops_its_token_exchange(hass: HomeAssistant) -> None:
    flow = LocalThingsConfigFlow()
    flow.hass = hass
    task = hass.async_create_task(asyncio.sleep(30))
    flow._token_task = task

    flow.async_remove()
    await asyncio.sleep(0)

    assert flow._token_stop.is_set()
    assert task.cancelled()
