"""AI Comfort can be left through the preset menu (review M3)."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.localthings.climate import PRESET_AI_COMFORT, LocalThingsClimate
from custom_components.localthings.registry.by_type import resolve
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import ClimateDesc
from tests.conftest import _load_device
from tests.test_subdevice_discovery import _coordinator

DEVICE_TYPES = ("oic.wk.d", "oic.d.airconditioner")
MODE = "/mode/vs/0"


def _climate(hass: HomeAssistant, name: str, overrides: dict | None = None) -> LocalThingsClimate:
    resources = _load_device(name)
    for href, fields in (overrides or {}).items():
        resources[href] = {**resources[href], **fields}
    coordinator = _coordinator(hass)
    for href, rep in resources.items():
        coordinator._observe.apply(href, rep, source="poll")
    reg = resolve(resources, device_types=DEVICE_TYPES)
    assert reg is not None
    coordinator.bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    coordinator.async_send_command = AsyncMock()
    bound = next(b for b in coordinator.bound if isinstance(b.desc, ClimateDesc))
    return LocalThingsClimate(coordinator, bound)


def _sent(climate: LocalThingsClimate) -> list:
    # _climate replaced the coordinator's async_send_command with an AsyncMock.
    send = cast(AsyncMock, climate.coordinator.async_send_command)
    return [call.args[1] for call in send.call_args_list]


# ---------------------------------------------------------------------------
# M3: leaving AI Comfort through the preset menu
# ---------------------------------------------------------------------------

_IN_AI_COMFORT = {MODE: {"x.com.samsung.da.modes": ["AIComfort"]}}


@pytest.mark.parametrize("preset", ["none", "sleep"])
async def test_choosing_another_preset_leaves_ai_comfort_for_plain_auto(hass, preset):
    """A-CAWW: the unit has a plain Auto, which AI Comfort overlays. Writing
    only the convenient mode left /mode/vs/0 on AIComfort, so the card
    snapped back to AI Comfort."""
    climate = _climate(hass, "airconditioner_caww_tp2", _IN_AI_COMFORT)
    assert climate.preset_mode == PRESET_AI_COMFORT

    await climate.async_set_preset_mode(preset)

    code = "Off" if preset == "none" else "Sleep"
    assert _sent(climate) == [("mode", "Auto"), ("preset", code)]


async def test_a_preset_outside_ai_comfort_does_not_touch_the_mode(hass):
    climate = _climate(hass, "airconditioner_caww_tp2")
    await climate.async_set_preset_mode("sleep")
    assert _sent(climate) == [("preset", "Sleep")]


async def test_choosing_ai_comfort_still_writes_the_primary_mode(hass):
    climate = _climate(hass, "airconditioner_caww_tp2")
    await climate.async_set_preset_mode(PRESET_AI_COMFORT)
    assert _sent(climate) == [("mode", "AIComfort")]


async def test_a_unit_without_plain_auto_leaves_for_its_first_mode(hass):
    """The AI Air Combo ventilator (#551) has no plain Auto, and this entity
    has only ever seen it in AI Comfort (the dump's own state)."""
    climate = _climate(hass, "airconditioner_tp1x_rhs")
    assert climate.preset_mode == PRESET_AI_COMFORT

    await climate.async_set_preset_mode("quiet")

    assert _sent(climate) == [("mode", "AutoVentilation"), ("preset", "Quiet")]


async def test_a_unit_without_plain_auto_goes_back_to_its_previous_mode(hass):
    climate = _climate(
        hass, "airconditioner_tp1x_rhs", {MODE: {"x.com.samsung.da.modes": ["FreshAirIntake"]}}
    )
    climate.async_write_ha_state = Mock()
    climate.coordinator._observe.apply(
        MODE, {"x.com.samsung.da.modes": ["AIComfort"]}, source="poll"
    )
    climate._handle_coordinator_update()
    assert climate.preset_mode == PRESET_AI_COMFORT

    await climate.async_set_preset_mode("none")

    assert _sent(climate) == [("mode", "FreshAirIntake"), ("preset", "Off")]
