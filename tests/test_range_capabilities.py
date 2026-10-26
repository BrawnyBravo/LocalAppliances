"""Tests for range/cooktop-oven combo support (issue #44)."""

from custom_components.localthings.registry.adapter import flatten
from custom_components.localthings.registry.by_type import for_device_by_model
from custom_components.localthings.registry.capabilities import range as range_caps
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import SelectDesc, SensorDesc, SwitchDesc
from tests.conftest import _load_device


def _range():
    resources = _load_device("range")
    info = resources["/information/vs/0"]
    reg = for_device_by_model(
        info["x.com.samsung.da.modelNum"],
        info["x.com.samsung.da.description"],
    )
    return reg, resources


def _state():
    reg, resources = _range()
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    return flatten(bound, resources)


def test_range_model_resolves_to_range_registry():
    reg, _ = _range()
    assert reg is not None and reg.name == "range"


def test_no_unbound_hrefs():
    """Every resource in the issue #44 dump binds or is ignored -- clears the
    coverage-gap repair."""
    reg, resources = _range()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_expected_entities_present():
    state = _state()
    for key in (
        "power_switch",
        "oven_setpoint",
        "current_temp_c",
        "oven_mode",
        "machine_state",
        "door_open",
        "cloud_connected",
        "cooktop_state",
        "cooktop_safety_shutoff_enabled",
        "burner_0_power_level",
        "burner_0_state",
        "burner_0_hot_surface",
        "burner_3_power_level",
        "burner_3_state",
        "burner_3_hot_surface",
    ):
        assert key in state, key


def test_unreported_burners_gated_out():
    """Dump reports numberOfBurners=4 (indices 0-3) -- burner slots 4/5 of
    MAX_BURNERS must not appear as entities."""
    state = _state()
    for key in ("burner_4_power_level", "burner_5_power_level"):
        assert key not in state, key


def test_burner_power_level_write_sends_only_that_burner():
    """Deliberately changed from the old read-modify-write test, which
    asserted every sibling burner's cached level was re-sent. A cache that
    is a poll behind (a burner turned down or off at the knob since) would
    have pushed that burner back to its old heat level. The write now names
    only the burner being changed; the device's state for the rest is left
    alone."""
    desc = next(
        e
        for e in range_caps.COOKTOP_STATUS.entities
        if e.key == "burner_1_power_level" and isinstance(e, SelectDesc)
    )
    rep = {
        "burnerList": [
            {"burnerNumber": 0, "powerLevel": "7", "operationState": "run", "timer": 0},
            {"burnerNumber": 1, "powerLevel": "0", "operationState": "ready", "timer": 0},
        ]
    }
    assert desc.write_fn is not None
    result = desc.write_fn("boost", rep)
    assert result is not None
    path, body = result
    assert path == ["cooktop", "status", "vs", "0"]
    assert body == {"burnerList": [{"burnerNumber": 1, "powerLevel": "boost"}]}
    # The cached rep itself is not mutated.
    assert rep["burnerList"][1]["powerLevel"] == "0"


def test_burner_hot_surface_unknown_when_burner_missing_from_list():
    """A burnerList that doesn't carry this burner (e.g. the one-burner
    optimistic entry a power write leaves until the next poll) is no
    evidence the surface is cool."""
    desc = next(e for e in range_caps.COOKTOP_STATUS.entities if e.key == "burner_0_hot_surface")
    assert desc.value_fn([{"burnerNumber": 1, "hotSurfaceState": "normal"}]) is None
    assert desc.value_fn(None) is None


def test_burner_power_level_write_rejects_missing_burner():
    desc = next(
        e
        for e in range_caps.COOKTOP_STATUS.entities
        if e.key == "burner_2_power_level" and isinstance(e, SelectDesc)
    )
    rep = {"burnerList": [{"burnerNumber": 0, "powerLevel": "0"}]}
    assert desc.write_fn is not None
    assert desc.write_fn("5", rep) is None


def test_burner_hot_surface_true_when_not_normal():
    desc = next(e for e in range_caps.COOKTOP_STATUS.entities if e.key == "burner_0_hot_surface")
    assert desc.value_fn([{"burnerNumber": 0, "hotSurfaceState": "hot"}]) is True
    assert desc.value_fn([{"burnerNumber": 0, "hotSurfaceState": "normal"}]) is False


def test_burner_pan_detected():  # issue #86
    desc = next(e for e in range_caps.COOKTOP_STATUS.entities if e.key == "burner_0_pan_detected")
    assert desc.value_fn([{"burnerNumber": 0, "panDetection": True}]) is True
    assert desc.value_fn([{"burnerNumber": 0, "panDetection": False}]) is False
    assert desc.value_fn([{"burnerNumber": 1, "panDetection": True}]) is False  # different burner


def test_cooktop_power_is_read_only():  # issue #86
    desc = next(e for e in range_caps.COOKTOP_STATUS.entities if e.key == "cooktop_power")
    assert desc.value_fn("On") is True
    assert desc.value_fn("Off") is False
    assert not hasattr(desc, "write_fn")  # BinarySensorDesc has no write path at all


def test_cooktop_child_lock_write():  # issue #86
    desc = next(
        e
        for e in range_caps.COOKTOP_STATUS.entities
        if e.key == "cooktop_child_lock" and isinstance(e, SwitchDesc)
    )
    assert desc.value_fn("on") is True
    assert desc.value_fn("off") is False
    assert desc.write_fn is not None
    result = desc.write_fn("On", {})
    assert result is not None
    path, body = result
    assert path == ["cooktop", "status", "vs", "0"]
    assert body == {"childLock": "on"}
    assert desc.write_fn("Bogus", {}) is None


def test_probe_status_temperature_unit_reads_live_field():  # issue #86
    desc = next(
        e
        for e in range_caps.PROBE_STATUS.entities
        if e.key == "probe_temperature" and isinstance(e, SensorDesc)
    )
    assert desc.unit_fn is not None
    assert desc.unit_fn({"temperatureUnit": "C"}) == "°C"
    assert desc.unit_fn({"temperatureUnit": "F"}) == "°F"
    assert desc.unit_fn({}) == "°C"


def test_probe_status_connected_value_fn():  # issue #86
    desc = next(e for e in range_caps.PROBE_STATUS.entities if e.key == "probe_connected")
    assert desc.value_fn("Connected") is True
    assert desc.value_fn("Disconnected") is False


def test_nx58k7850ss_has_no_unbound_hrefs():
    """Issue #624's Flex Duo range reports the oven's diagnosisStart shape
    on /diagnosis/vs/0, which raised the coverage repair until the range
    bound it the way the oven registry does."""
    from custom_components.localthings.registry.by_type import resolve

    resources = _load_device("range_nx58k7850ss")
    reg = resolve(resources, device_types=("oic.wk.d", "oic.d.range"))
    assert reg is not None and reg.name == "range"
    unbound = []
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []
    assert flatten(bound, resources)["diagnosis_status"] == "ready"
