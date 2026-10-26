"""The canonical-view memo must not keep a view built across a cache change
(review finding L1): a notify on another thread that lands while the event
loop is building the view clears the memo, and the loop must not then store
its now-stale view on top."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings import coordinator as coordinator_mod
from custom_components.localthings.const import (
    CONF_HOST,
    CONF_LEAF_CERT_PEM,
    CONF_LEAF_KEY_PEM,
    CONF_PORT,
    DOMAIN,
)
from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.registry.subdevices import MAIN

ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_PORT: 49154,
    CONF_LEAF_CERT_PEM: "TEST-LEAF-CERT",
    CONF_LEAF_KEY_PEM: "TEST-LEAF-KEY",
}


async def test_view_built_across_a_cache_change_is_not_memoized(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="localthings_CANON-TEST")
    entry.add_to_hass(hass)
    coord = LocalThingsCoordinator(hass, entry)

    real_view = coordinator_mod.canonical_view
    builds: list[int] = []

    def _view(subdevice, resources, subdevices):
        builds.append(1)
        view = real_view(subdevice, resources, subdevices)
        if len(builds) == 1:
            # A notify applied on another thread mid-build.
            coord._on_cache_changed(True, "observe")
        return view

    monkeypatch.setattr(coordinator_mod, "canonical_view", _view)

    coord.canonical_resources(MAIN)
    coord.canonical_resources(MAIN)
    assert len(builds) == 2  # the first, stale build was not kept

    coord.canonical_resources(MAIN)
    assert len(builds) == 2  # an undisturbed build is memoized as before
