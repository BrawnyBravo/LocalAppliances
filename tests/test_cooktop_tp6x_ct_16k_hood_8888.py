"""NZ30K7570RS cooktop with a paired NK9300KM hood over 8888 (issue #676).

The hood answers on /devices/1, the slot the NZ36K7570R reports empty (#642).
Paired, it must read as a hood rather than a second cooktop.
"""

import json
from pathlib import Path

from custom_components.localthings.legacy_http import TP6X_CT, to_resources
from custom_components.localthings.registry.adapter import _key, flatten
from custom_components.localthings.registry.capabilities.cooktop import (
    LEGACY_HOOD_MODE,
    LEGACY_HOOD_POWER,
)
from custom_components.localthings.registry.subdevices import Subdevice
from tests.conftest import _discover_full, _load_device_full

NAME = "cooktop_tp6x_ct_16k_hood_8888"
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / f"{NAME}_device.json").read_text(encoding="utf-8")
)


def test_the_fixture_is_the_translation_of_its_bodies():
    device0 = {e["href"]: e["rep"] for e in FIXTURE["device0"]}
    assert device0 == to_resources(FIXTURE["bodies"], TP6X_CT)
    hood = Subdevice(kind="indexed", key="1", seed_path=("device", "1"))
    seed = {hood.to_canonical(e["href"]): e["rep"] for e in FIXTURE["seeds"]["/device/1"]}
    seed.pop("/connected/vs/0")
    assert seed == to_resources(FIXTURE["device_bodies"]["1"], TP6X_CT)


def _discover():
    resources, oic_res, seeds = _load_device_full(NAME)
    bound, materialized, _skipped, full, _name = _discover_full(resources, oic_res, seeds)
    state = flatten(bound, full)
    return bound, materialized, state


def test_the_hood_is_subdevice_1_with_hood_entities_only():
    bound, materialized, _state = _discover()

    assert [s.key for s in materialized] == ["1"]
    hood_keys = {b.desc.key for b in bound if b.subdevice.key == "1"}
    assert {
        "paired_hood_connected",
        "paired_hood_fan_setting",
        "paired_hood_light",
        "paired_hood_model",
        "paired_hood_power",
        "paired_hood_shutoff_timer_state",
        "paired_hood_shutoff_timer_set",
        "paired_hood_shutoff_timer_remaining",
    } <= hood_keys
    assert not any(k.startswith(("burner_", "main_timer")) for k in hood_keys)
    assert "any_burner_active" not in hood_keys
    assert "power_state" not in hood_keys


def test_the_hood_reads_its_options():
    bound, _materialized, state = _discover()
    hood = {b.desc.key: state[_key(b)] for b in bound if b.subdevice.key == "1"}

    assert hood["paired_hood_connected"] is True
    assert hood["paired_hood_fan_setting"] == "low"
    assert hood["paired_hood_light"] is False
    assert hood["paired_hood_model"] == "NK9300KM"
    assert hood["paired_hood_power"] is False
    assert hood["paired_hood_shutoff_timer_state"] == "Ready"
    assert hood["paired_hood_shutoff_timer_set"] == 0
    assert hood["paired_hood_shutoff_timer_remaining"] == 0


# /devices/1's Mode options from the reporter's second dump, taken with the
# hood running.
_RUNNING_OPTIONS = [
    "DeviceType_NK9300KM",
    "Bluetooth_On",
    "FanSpeed_2",
    "Lamp_On",
    "ShutOffTimerSet_10",
    "ShutOffTimerCurrent_9",
    "ShutOffTimerState_Run",
]


def test_the_running_hood_reads_its_options():
    hood = {desc.key: desc.value_fn(_RUNNING_OPTIONS) for desc in LEGACY_HOOD_MODE.entities}

    assert hood["paired_hood_fan_setting"] == "medium"
    assert hood["paired_hood_light"] is True
    assert hood["paired_hood_shutoff_timer_state"] == "Run"
    assert hood["paired_hood_shutoff_timer_set"] == 10
    assert hood["paired_hood_shutoff_timer_remaining"] == 9


# The reporter's last dump, taken once the hood had turned off: power reads
# Off, the fan keeps its High setting and the light, which runs on its own,
# stays on.
_SHUTOFF_POWER = "Off"
_SHUTOFF_OPTIONS = [
    "DeviceType_NK9300KM",
    "Bluetooth_On",
    "FanSpeed_3",
    "Lamp_On",
    "ShutOffTimerSet_10",
    "ShutOffTimerCurrent_0",
    "ShutOffTimerState_Ready",
]


def test_the_hood_after_shutoff_keeps_its_fan_setting_and_light():
    (power,) = LEGACY_HOOD_POWER.entities
    hood = {desc.key: desc.value_fn(_SHUTOFF_OPTIONS) for desc in LEGACY_HOOD_MODE.entities}

    assert power.value_fn(_SHUTOFF_POWER) is False
    assert hood["paired_hood_fan_setting"] == "high"
    assert hood["paired_hood_light"] is True
    assert hood["paired_hood_shutoff_timer_state"] == "Ready"
    assert hood["paired_hood_shutoff_timer_set"] == 10
    assert hood["paired_hood_shutoff_timer_remaining"] == 0


def test_the_cooktop_keeps_its_burners():
    bound, _materialized, _state = _discover()
    main_keys = {b.desc.key for b in bound if b.subdevice.key != "1"}

    assert {"any_burner_active", "burner_3_pan_size", "main_timer_set", "power_state"} <= main_keys
    assert not any(k.startswith("paired_hood_") for k in main_keys)
