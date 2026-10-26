"""When a command write is retried (review finding L4).

A write whose answer timed out has been sent and may already have run.
Re-sending a setpoint is harmless; re-sending a start, a drum clean or a
cook-start batch can run it twice, so those are reported instead. A 401 from
the 8888 bridge means the device token is no longer accepted, which a retry
with the same token cannot fix, so it starts reauthentication.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import (
    CONF_HOST,
    CONF_LEAF_CERT_PEM,
    CONF_LEAF_KEY_PEM,
    CONF_PORT,
    DOMAIN,
)
from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.registry.capabilities import laundry
from custom_components.localthings.registry.capability import Capability
from custom_components.localthings.registry.discovery import BoundEntity
from custom_components.localthings.transport import AuthRejected, Transport

ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 49154,
    CONF_LEAF_CERT_PEM: "TEST-LEAF-CERT",
    CONF_LEAF_KEY_PEM: "TEST-LEAF-KEY",
}


class _Session:
    """Answers each write from a script: an exception to raise, or a code."""

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.writes: list[list[str]] = []

    def write(self, path_segs, body, timeout=None):
        self.writes.append(list(path_segs))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step, None

    def pace(self) -> None:
        pass


@pytest.fixture
def coordinator(hass: HomeAssistant) -> LocalThingsCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="localthings_RETRY-TEST")
    entry.add_to_hass(hass)
    coord = LocalThingsCoordinator(hass, entry)
    coord.async_request_refresh = AsyncMock()
    coord._RECONNECT_PAUSE_S = 0
    return coord


def _wire(
    coord: LocalThingsCoordinator, session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing drops the session; reconnecting brings the same fake back."""
    # _Session only scripts the write path the retry logic touches, not the
    # whole Transport protocol.
    transport = cast(Transport, session)
    coord._session = transport

    def _close() -> None:
        coord._session = None

    def _connect() -> None:
        coord._session = transport

    monkeypatch.setattr(coord, "_close_session", _close)
    monkeypatch.setattr(coord, "_connect_session", _connect)


async def test_a_timed_out_non_idempotent_write_is_not_re_sent(
    coordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _Session([TimeoutError("no ACK"), 0x44])
    _wire(coordinator, session, monkeypatch)

    with pytest.raises(HomeAssistantError) as err:
        await coordinator._async_put(
            ["course", "vs", "0"], {"a": 1}, "/course/vs/0", idempotent=False
        )

    assert err.value.translation_key == "command_unconfirmed"
    assert len(session.writes) == 1


async def test_a_timed_out_setpoint_is_still_retried(
    coordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _Session([TimeoutError("no ACK"), 0x44])
    _wire(coordinator, session, monkeypatch)

    await coordinator._async_put(["course", "vs", "0"], {"a": 1}, "/course/vs/0")

    assert len(session.writes) == 2


async def test_a_non_idempotent_write_on_a_dead_session_is_retried(
    coordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead session is known before the request goes out: nothing ran."""
    session = _Session([ConnectionError("session closed"), 0x44])
    _wire(coordinator, session, monkeypatch)

    await coordinator._async_put(["course", "vs", "0"], {"a": 1}, "/course/vs/0", idempotent=False)

    assert len(session.writes) == 2


async def test_a_refused_device_token_starts_reauth_instead_of_retrying(
    hass: HomeAssistant, coordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _Session([AuthRejected("401"), 0x44])
    _wire(coordinator, session, monkeypatch)
    start_reauth = Mock()
    coordinator._entry.async_start_reauth = start_reauth

    with pytest.raises(ConfigEntryAuthFailed) as err:
        await coordinator._async_put(["devices", "0"], {"a": 1}, "/devices/0")

    assert err.value.translation_key == "command_auth_rejected"
    assert len(session.writes) == 1
    start_reauth.assert_called_once_with(hass)


async def test_a_readable_setting_write_is_treated_as_idempotent(coordinator) -> None:
    href = "/course/vs/0"
    coordinator._observe.apply(href, {"x.com.samsung.da.options": ["Course_16"]}, source="poll")
    put = AsyncMock()
    coordinator._async_put = put

    desc = laundry.cycle_select(translation_key="dryer_cycle", icon="x")
    await coordinator.async_send_command(
        BoundEntity(href=href, capability=Capability(), desc=desc), "1D"
    )

    assert put.await_args is not None
    assert put.await_args.kwargs["idempotent"] is True
