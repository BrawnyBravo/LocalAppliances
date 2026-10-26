"""The climate entity reports an unreadable mode as unknown, not Auto
(review L2)."""

from __future__ import annotations

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant

from custom_components.localthings.climate import LocalThingsClimate
from custom_components.localthings.registry.by_type import resolve
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import ClimateDesc
from tests.conftest import _load_device
from tests.test_subdevice_discovery import _coordinator

MODE = "/mode/vs/0"
# A ventilator: no Auto among its modes, so a guessed Auto is a state the
# unit cannot be in.
NAME = "airconditioner_aca_kr_tp2_21_an9000"


def _climate(hass: HomeAssistant, mode_rep: dict) -> LocalThingsClimate:
    resources = _load_device(NAME)
    resources["/power/vs/0"] = {**resources["/power/vs/0"], "x.com.samsung.da.power": "On"}
    coordinator = _coordinator(hass)
    for href, rep in resources.items():
        coordinator._observe.apply(href, rep, source="poll")
    reg = resolve(resources, device_types=("oic.wk.d", "oic.d.airconditioner"))
    assert reg is not None
    coordinator.bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    bound = next(b for b in coordinator.bound if isinstance(b.desc, ClimateDesc))
    climate = LocalThingsClimate(coordinator, bound)
    coordinator._observe.apply(MODE, mode_rep, source="poll")
    return climate


@pytest.mark.parametrize(
    "mode_rep",
    [
        {"x.com.samsung.da.modes": []},
        {"x.com.samsung.da.modes": ["SomethingNew"]},
        {"x.com.samsung.da.modes": ["HOMECARE_WIZARD_V2"]},
    ],
    ids=["empty", "unmapped", "option-flag"],
)
def test_an_unreadable_mode_is_unknown_not_auto(hass, mode_rep):
    climate = _climate(hass, mode_rep)
    assert HVACMode.AUTO not in climate.hvac_modes
    assert climate.hvac_mode is None


def test_a_readable_mode_is_unchanged(hass):
    climate = _climate(hass, {"x.com.samsung.da.modes": ["Ventilation"]})
    assert climate.hvac_mode == HVACMode.FAN_ONLY
