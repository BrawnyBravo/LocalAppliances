"""Climate controls follow what each unit actually has (review M2)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.core import HomeAssistant

from custom_components.localthings.climate import LocalThingsClimate
from custom_components.localthings.registry.by_type import resolve
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import ClimateDesc
from tests.conftest import _load_device
from tests.test_subdevice_discovery import _coordinator

DEVICE_TYPES = ("oic.wk.d", "oic.d.airconditioner")


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


# ---------------------------------------------------------------------------
# M2: feature flags
# ---------------------------------------------------------------------------


def test_a_ventilator_without_temperature_or_presets_offers_neither(hass):
    """ACA-KR-TP2-21-AN9000: no /temperature* resource, no convenient mode,
    no AIComfort. A setpoint control would show HA's default 7-35 degree range
    with no value and every write would be rejected; the preset menu would be
    empty."""
    climate = _climate(hass, "airconditioner_aca_kr_tp2_21_an9000")
    features = climate.supported_features

    assert climate.preset_modes == []
    assert not features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert not features & ClimateEntityFeature.PRESET_MODE
    assert features & ClimateEntityFeature.TURN_ON
    assert features & ClimateEntityFeature.TURN_OFF
    # Fan follows the same rule: on only when there are speeds to offer.
    assert bool(features & ClimateEntityFeature.FAN_MODE) == bool(climate.fan_modes)


@pytest.mark.parametrize(
    "name", ["airconditioner_caww_tp2", "airconditioner_tp2x_rac_20k", "airconditioner_tp1x_rhs"]
)
def test_a_full_unit_keeps_every_control(hass, name):
    climate = _climate(hass, name)
    features = climate.supported_features
    assert features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert features & ClimateEntityFeature.FAN_MODE
    assert features & ClimateEntityFeature.PRESET_MODE


def test_the_setpoint_stays_while_its_rep_is_momentarily_empty(hass):
    """Judged by the href being known, not by its value, so the control does
    not flicker on a stub poll."""
    climate = _climate(hass, "airconditioner_caww_tp2")
    href = next(
        h for h in ("/temperatures/vs/0", "/temperature/desired/0") if h in climate._resources
    )
    climate.coordinator._observe.apply(href, {"href": href}, source="poll")
    assert climate.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
