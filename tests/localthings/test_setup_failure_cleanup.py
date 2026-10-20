"""A setup that fails after the first refresh must not leave a live
coordinator behind (review finding M4).

Home Assistant only runs an entry's async_on_unload callbacks when its
setup raises, never async_unload_entry, so without explicit cleanup the
coordinator kept its session and threads open and stayed in hass.data,
where the raw services could still route writes to it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import DOMAIN

from .conftest import ENTRY_DATA, MOCK_SERIAL

_COORD = "custom_components.localthings.coordinator.LocalThingsCoordinator"


@pytest.mark.parametrize(
    "target",
    [
        "custom_components.localthings.async_load_instance_names",
        "custom_components.localthings._drop_washer_entities_from_filters",
    ],
)
async def test_failure_after_first_refresh_closes_and_forgets_coordinator(
    hass: HomeAssistant, mock_coordinator_session, target
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=f"localthings_{MOCK_SERIAL}")
    entry.add_to_hass(hass)

    close = AsyncMock()
    with (
        patch(target, side_effect=RuntimeError("boom")),
        patch(f"{_COORD}.async_close", close),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    close.assert_awaited()


async def test_failed_forward_of_platforms_closes_coordinator(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=f"localthings_{MOCK_SERIAL}")
    entry.add_to_hass(hass)

    close = AsyncMock()
    with (
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(side_effect=ImportError("platform failed to import")),
        ),
        patch(f"{_COORD}.async_close", close),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    close.assert_awaited()
