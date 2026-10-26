"""A different appliance answering at an entry's address is surfaced as a
Repair, and cleared when the right one answers again (review finding L3)."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import (
    CONF_HOST,
    CONF_LEAF_CERT_PEM,
    CONF_LEAF_KEY_PEM,
    CONF_PORT,
    DOMAIN,
)
from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.credentials import DeviceIdentityMismatch

ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 49154,
    CONF_LEAF_CERT_PEM: "TEST-LEAF-CERT",
    CONF_LEAF_KEY_PEM: "TEST-LEAF-KEY",
}


@pytest.fixture
def coordinator(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> LocalThingsCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="localthings_IDENTITY-TEST")
    entry.add_to_hass(hass)
    coord = LocalThingsCoordinator(hass, entry)
    monkeypatch.setattr(coord, "_close_session", lambda: None)
    return coord


async def test_identity_mismatch_raises_and_clears_a_repair(
    hass: HomeAssistant, coordinator: LocalThingsCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _poll():
        raise DeviceIdentityMismatch("192.0.2.10 authenticated as a different OCF device")

    monkeypatch.setattr(coordinator, "_poll_once", _poll)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    issue_id = f"device_identity_mismatch_{coordinator._entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "device_identity_mismatch"
    assert issue.translation_placeholders["host"] == "192.0.2.10"

    coordinator._mark_device_answered()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_identity_mismatch_is_not_retried_as_a_dead_session(
    hass: HomeAssistant, coordinator: LocalThingsCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconnecting only reaches the same wrong appliance again."""
    calls: list[int] = []

    def _poll():
        calls.append(1)
        raise DeviceIdentityMismatch("wrong appliance")

    monkeypatch.setattr(coordinator, "_poll_once", _poll)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert len(calls) == 1
