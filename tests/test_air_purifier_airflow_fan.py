"""HA fan-entity mapping tests for the ARTIK051_TVTL air purifier (issue #56)."""

from typing import ClassVar, cast

import pytest
from homeassistant.components.fan import FanEntityFeature

from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.fan import LocalThingsAirflowFan
from custom_components.localthings.registry.by_type import air_purifier
from custom_components.localthings.registry.capabilities.air_purifier import HREF_AIRFLOW
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import FanDesc
from tests.conftest import _load_device


class _FakeCoordinator:
    device_key = "TEST-AIRFLOW-SERIAL"
    device_info: ClassVar[dict] = {}
    data: ClassVar[dict] = {}

    def __init__(self, resources):
        self.last_resources = resources
        self.commands = []

    def resource(self, href):
        return self.last_resources.get(href, {})

    def canonical_resources(self, subdevice):
        # Every bound entity in this test uses the default MAIN
        # subdevice, so the canonical view is just the raw snapshot
        # (issue #177 -- see LocalThingsEntity._resources).
        return self.last_resources

    async def async_send_command(self, bound, payload):
        self.commands.append((bound, payload))


def _entity(resources, coordinator=None):
    bound = discover(
        resources,
        air_purifier.REGISTRY.capabilities,
        air_purifier.REGISTRY.pattern_capabilities,
    )
    fan_bound = next(
        item for item in bound if isinstance(item.desc, FanDesc) and item.href == HREF_AIRFLOW
    )
    return LocalThingsAirflowFan(
        cast(LocalThingsCoordinator, coordinator or _FakeCoordinator(resources)),
        fan_bound,
    )


def test_power_off_maps_to_zero_percent_and_three_speeds():
    entity = _entity(_load_device("air_purifier"))
    assert entity.is_on is False
    assert entity.speed_count == 3
    assert entity.percentage == 0


def test_speeds_map_to_percentages_and_auto_sleep_to_presets():
    """Confirmed via issue #56's second, properly-spaced diagnostics round:
    /airflow/0's speed is a clean 0-4 code across Auto/Sleep/Low/Medium/High.
    Only Low/Medium/High are speeds (review L6): Auto and Sleep used to read
    back as 20% and 40%, and setting 20% chose Auto."""
    resources = _load_device("air_purifier")
    resources["/power/0"]["value"] = True

    for code, percentage, preset in (
        (0, None, "auto"),
        (1, None, "sleep"),
        (2, 33, None),
        (3, 66, None),
        (4, 100, None),
    ):
        resources["/airflow/0"]["speed"] = code
        entity = _entity(resources)
        assert entity.percentage == percentage, code
        assert entity.preset_mode == preset, code
    assert entity.preset_modes == ["auto", "sleep"]
    assert entity.supported_features & FanEntityFeature.PRESET_MODE


@pytest.mark.parametrize(("percentage", "code"), [(1, 2), (20, 2), (40, 3), (66, 3), (100, 4)])
async def test_any_positive_percentage_is_a_real_speed(percentage, code):
    resources = _load_device("air_purifier")
    resources["/power/0"]["value"] = True
    coordinator = _FakeCoordinator(resources)

    await _entity(resources, coordinator).async_set_percentage(percentage)

    assert coordinator.commands[-1][1] == ("speed", code)


@pytest.mark.parametrize(("preset", "code"), [("auto", 0), ("sleep", 1)])
async def test_presets_write_their_speed_code_and_power_on(preset, code):
    resources = _load_device("air_purifier")
    resources["/power/0"]["value"] = False
    coordinator = _FakeCoordinator(resources)

    await _entity(resources, coordinator).async_set_preset_mode(preset)

    assert [payload for _, payload in coordinator.commands] == [
        ("power", True, "/power/0"),
        ("speed", code),
    ]


async def test_turn_on_with_a_preset():
    resources = _load_device("air_purifier")
    coordinator = _FakeCoordinator(resources)

    await _entity(resources, coordinator).async_turn_on(preset_mode="sleep")

    assert coordinator.commands[-1][1] == ("speed", 1)


async def test_power_write_prefers_standard_resource_when_both_exist():
    """Both /power/0 and /power/vs/0 are present on this family's dumps --
    /power/0 must win, matching common.POWER_GENERIC's own preference (the
    power_switch entity is unconditionally bound to /power/0 whenever it's
    present, so writing here to /power/vs/0 first would leave the two
    entities disagreeing until the next poll)."""
    resources = _load_device("air_purifier")
    coordinator = _FakeCoordinator(resources)
    entity = _entity(resources, coordinator)

    await entity.async_turn_on()

    assert coordinator.commands[-1][1] == ("power", True, "/power/0")


async def test_power_write_falls_back_to_vendor_resource():
    resources = _load_device("air_purifier")
    resources.pop("/power/0")
    coordinator = _FakeCoordinator(resources)
    entity = _entity(resources, coordinator)

    await entity.async_turn_off()

    assert coordinator.commands[-1][1] == ("power", False, "/power/vs/0")


async def test_set_percentage_writes_raw_speed_code():
    resources = _load_device("air_purifier")
    resources["/power/0"]["value"] = True
    coordinator = _FakeCoordinator(resources)
    entity = _entity(resources, coordinator)

    await entity.async_set_percentage(33)

    assert coordinator.commands[-1][1] == ("speed", 2)


async def test_set_percentage_zero_turns_off():
    resources = _load_device("air_purifier")
    resources["/power/0"]["value"] = True
    coordinator = _FakeCoordinator(resources)
    entity = _entity(resources, coordinator)

    await entity.async_set_percentage(0)

    assert coordinator.commands[-1][1] == ("power", False, "/power/0")
