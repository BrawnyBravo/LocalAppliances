"""Direct tests of the time, switch and binary-sensor platform classes
(review L9): until now they were covered only through capability-level
tests that never built the entity."""

from __future__ import annotations

import datetime
from typing import ClassVar, cast

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.localthings.binary_sensor import LocalThingsBinarySensor
from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.registry.capability import Capability
from custom_components.localthings.registry.discovery import BoundEntity
from custom_components.localthings.registry.entities import (
    BinarySensorDesc,
    SwitchDesc,
    TimeDesc,
)
from custom_components.localthings.switch import LocalThingsSwitch
from custom_components.localthings.time import LocalThingsTime

HREF = "/thing/vs/0"


class _FakeCoordinator:
    device_key = "TEST-PLATFORM"
    instance_names: ClassVar[dict] = {}

    def __init__(self, data=None, resources=None):
        self.data = data or {}
        self.last_resources = resources or {}
        self.sent: list = []

    def resource(self, href):
        return self.last_resources.get(href)

    def entity_rep(self, href):
        return self.last_resources.get(href) or {}

    def canonical_resources(self, _subdevice):
        return self.last_resources

    async def async_send_command(self, bound, value):
        self.sent.append(value)


def _build(cls, desc, coordinator):
    bound = BoundEntity(href=HREF, capability=Capability(href=HREF, entities=(desc,)), desc=desc)
    return cls(cast(LocalThingsCoordinator, coordinator), bound)


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------


def test_time_passes_a_wall_clock_value_straight_through():
    coordinator = _FakeCoordinator({"alarm": datetime.time(6, 45)})
    entity = _build(LocalThingsTime, TimeDesc(key="alarm", field="t"), coordinator)
    assert entity.native_value == datetime.time(6, 45)


def test_time_is_none_without_a_value():
    entity = _build(LocalThingsTime, TimeDesc(key="alarm", field="t"), _FakeCoordinator())
    assert entity.native_value is None


async def test_time_shows_a_utc_instant_in_local_time(hass: HomeAssistant):
    """A projected duration arrives as a UTC instant (operational.
    delay_finish_at) and has to be shown on the local clock."""
    await hass.config.async_set_time_zone("Asia/Tokyo")  # UTC+9, no DST
    instant = datetime.datetime(2026, 1, 15, 23, 30, tzinfo=datetime.UTC)
    coordinator = _FakeCoordinator({"finish_at": instant})
    entity = _build(LocalThingsTime, TimeDesc(key="finish_at", field="t"), coordinator)
    assert entity.native_value == datetime.time(8, 30)


async def test_time_writes_the_raw_value_without_a_payload_fn():
    coordinator = _FakeCoordinator()
    entity = _build(LocalThingsTime, TimeDesc(key="alarm", field="t"), coordinator)
    await entity.async_set_value(datetime.time(7, 15))
    assert coordinator.sent == [datetime.time(7, 15)]


async def test_time_payload_fn_gets_the_value_and_the_current_local_time(hass: HomeAssistant):
    await hass.config.async_set_time_zone("Asia/Tokyo")
    seen = []

    def payload_fn(value, now):
        seen.append((value, now))
        return f"{value.hour:02d}{value.minute:02d}"

    coordinator = _FakeCoordinator()
    desc = TimeDesc(key="delay", field="t", payload_fn=payload_fn)
    entity = _build(LocalThingsTime, desc, coordinator)

    before = dt_util.now()
    await entity.async_set_value(datetime.time(21, 5))

    assert coordinator.sent == ["2105"]
    value, now = seen[0]
    assert value == datetime.time(21, 5)
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.timedelta(hours=9)
    assert now >= before


# ---------------------------------------------------------------------------
# switch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", [True, False, None])
def test_switch_reads_its_state_key(state):
    coordinator = _FakeCoordinator({"child_lock": state})
    entity = _build(LocalThingsSwitch, SwitchDesc(key="child_lock", field="l"), coordinator)
    assert entity.is_on is state


async def test_switch_writes_on_and_off():
    coordinator = _FakeCoordinator()
    entity = _build(LocalThingsSwitch, SwitchDesc(key="child_lock", field="l"), coordinator)
    await entity.async_turn_on()
    await entity.async_turn_off()
    assert coordinator.sent == ["On", "Off"]


def test_switch_device_class_and_attributes():
    rep = {"l": "On", "extra": 3}
    coordinator = _FakeCoordinator({"outlet": True}, {HREF: rep})
    desc = SwitchDesc(
        key="outlet",
        field="l",
        device_class="outlet",
        extra_state_attributes_fn=lambda rep, resources: {
            "extra": rep["extra"],
            "n": len(resources),
        },
    )
    entity = _build(LocalThingsSwitch, desc, coordinator)
    assert entity.device_class == SwitchDeviceClass.OUTLET
    assert entity.extra_state_attributes == {"extra": 3, "n": 1}


def test_switch_without_extras_has_no_attributes():
    entity = _build(LocalThingsSwitch, SwitchDesc(key="s", field="l"), _FakeCoordinator())
    assert entity.device_class is None
    assert entity.extra_state_attributes is None


# ---------------------------------------------------------------------------
# binary sensor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", [True, False, None])
def test_binary_sensor_reads_its_state_key(state):
    coordinator = _FakeCoordinator({"door": state})
    desc = BinarySensorDesc(key="door", field="d", device_class="door")
    entity = _build(LocalThingsBinarySensor, desc, coordinator)
    assert entity.is_on is state
    assert entity.device_class == BinarySensorDeviceClass.DOOR


def test_binary_sensor_without_a_device_class():
    desc = BinarySensorDesc(key="flag", field="f")
    entity = _build(LocalThingsBinarySensor, desc, _FakeCoordinator())
    assert entity.device_class is None


def test_unique_ids_carry_the_device_key_and_state_key():
    entity = _build(LocalThingsSwitch, SwitchDesc(key="child_lock", field="l"), _FakeCoordinator())
    assert entity.unique_id == "localthings_TEST-PLATFORM_child_lock"
