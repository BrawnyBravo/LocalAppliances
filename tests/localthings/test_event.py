"""Cycle and alert event entities (LocalAppliances addition, event.py)."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import CONF_DEVICE_TYPE, DOMAIN
from custom_components.localthings.event import (
    ALERT_ALARM,
    ALERT_DOOR,
    CYCLE_FINISHED,
    CYCLE_STARTED,
    CycleTracker,
    alarm_codes,
    new_alerts,
)
from custom_components.localthings.registry.capabilities.operational import OPERATIONAL_STATE
from custom_components.localthings.registry.entities import SensorDesc

from .conftest import ENTRY_DATA, FIXTURES

_PROGRESS = next(
    d for d in OPERATIONAL_STATE.entities if isinstance(d, SensorDesc) and d.key == "progress"
)
_OP = "/operational/state/vs/0"
_ALARMS = "/alarms/vs/0"


def _rep(state: str, progress: str) -> dict:
    return {"x.com.samsung.da.state": state, "x.com.samsung.da.progress": progress}


def _run(reps):
    """Feed reps through a fresh CycleTracker; return the events."""
    tracker = CycleTracker(_PROGRESS)
    return [tracker.update(rep) for rep in reps]


def test_cycle_first_reading_only_seeds() -> None:
    # Already finished, or already running, when HA starts: nothing fires.
    assert _run([_rep("Run", "Finish")]) == [None]
    assert _run([_rep("Run", "Wash")]) == [None]


def test_cycle_full_wash() -> None:
    events = _run(
        [
            _rep("Ready", "None"),
            _rep("Run", "Wash"),
            _rep("Run", "Rinse"),
            _rep("Run", "Finish"),
            _rep("Ready", "None"),
        ]
    )
    assert events == [None, CYCLE_STARTED, None, CYCLE_FINISHED, None]


def test_cycle_finish_seen_after_state_went_idle() -> None:
    """#345's washer: `state` idle by the time `progress` reads Finish."""
    events = _run([_rep("Run", "Wash"), _rep("Ready", "Finish"), _rep("Ready", "None")])
    assert events == [None, CYCLE_FINISHED, None]


def test_cycle_stuck_finish_fires_once() -> None:
    events = _run([_rep("Run", "Rinse")] + [_rep("Run", "Finish")] * 4)
    assert events.count(CYCLE_FINISHED) == 1


def test_cycle_pause_and_resume_is_one_cycle() -> None:
    events = _run(
        [
            _rep("Ready", "None"),
            _rep("Run", "Wash"),
            _rep("Pause", "Wash"),
            _rep("Run", "Wash"),
            _rep("Run", "Finish"),
        ]
    )
    assert events == [None, CYCLE_STARTED, None, None, CYCLE_FINISHED]


def test_cycle_finish_flapping_fires_once() -> None:
    events = _run(
        [_rep("Run", "Rinse"), _rep("Run", "Finish"), _rep("Ready", "None"), _rep("Run", "Finish")]
    )
    assert events.count(CYCLE_FINISHED) == 1


def test_cycle_delay_starts_when_washing_does() -> None:
    events = _run(
        [
            _rep("Ready", "None"),
            _rep("Run", "Delaywash"),
            _rep("Run", "Delaywash"),
            _rep("Run", "Wash"),
        ]
    )
    assert events == [None, None, None, CYCLE_STARTED]


def test_cycle_cancelled_then_new_cycle_starts_again() -> None:
    events = _run(
        [_rep("Run", "Wash"), _rep("Ready", "None"), _rep("Run", "Wash"), _rep("Run", "Finish")]
    )
    assert events == [None, None, CYCLE_STARTED, CYCLE_FINISHED]


def test_cycle_paused_at_startup_then_finishes() -> None:
    events = _run([_rep("Pause", "Rinse"), _rep("Run", "Rinse"), _rep("Run", "Finish")])
    assert events == [None, None, CYCLE_FINISHED]


def test_cycle_dryer_reset_tail_is_not_a_start() -> None:
    """#358's dryer resets progress to 'Drying' as `state` goes idle."""
    events = _run([_rep("Run", "Finish"), _rep("Ready", "Drying"), _rep("Ready", "None")])
    assert CYCLE_STARTED not in events


def test_alarm_codes_parse() -> None:
    assert alarm_codes("none") == frozenset()
    assert alarm_codes(None) == frozenset()
    assert alarm_codes("SNSF_Reached, DoorA_Opened") == {"SNSF_Reached", "DoorA_Opened"}


def test_new_alerts() -> None:
    assert new_alerts(None, frozenset({"DoorA_Opened"})) == []
    assert new_alerts(frozenset(), frozenset({"DoorA_Opened", "ErrorCode_4C"})) == [
        (ALERT_DOOR, "DoorA_Opened"),
        (ALERT_ALARM, "ErrorCode_4C"),
    ]
    # Still active, or cleared: nothing new.
    assert new_alerts(frozenset({"DoorA_Opened"}), frozenset({"DoorA_Opened"})) == []
    assert new_alerts(frozenset({"DoorA_Opened"}), frozenset()) == []


def _dishwasher_resources() -> dict:
    from custom_components.localthings.registry.batch import parse_device0_batch

    data = json.loads((FIXTURES / "dishwasher_device.json").read_text())
    return parse_device0_batch(data["device0"])


async def test_dishwasher_events_end_to_end(hass: HomeAssistant) -> None:
    """Set up a dishwasher entry, then drive a cycle and an alarm through
    real coordinator refreshes and check what the event entities report."""
    resources = _dishwasher_resources()
    # Start mid-cycle with no alarms, so the seed is "running, quiet".
    resources[_OP] = {**resources[_OP], **_rep("Run", "Wash")}
    resources[_ALARMS] = {"x.com.samsung.da.items": []}
    current = {"r": resources}

    entry = MockConfigEntry(
        domain=DOMAIN, data={**ENTRY_DATA, CONF_DEVICE_TYPE: "dishwasher"}, version=4
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.localthings.coordinator.LocalThingsCoordinator._connect_session"),
        patch(
            "custom_components.localthings.coordinator.LocalThingsCoordinator._poll_once",
            side_effect=lambda *a, **k: copy.deepcopy(current["r"]),
        ),
        patch("custom_components.localthings.coordinator.LocalThingsCoordinator._close_session"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        ent_reg = er.async_get(hass)
        rows = {
            e.unique_id.rsplit("_", 2)[-2]: e.entity_id
            for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
            if e.domain == "event"
        }
        assert set(rows) == {"cycle", "alert"}
        cycle_id, alert_id = rows["cycle"], rows["alert"]
        cycle = hass.states.get(cycle_id)
        alert = hass.states.get(alert_id)
        assert cycle is not None and cycle.state == "unknown"
        assert alert is not None and alert.state == "unknown"

        coordinator = hass.data[DOMAIN][entry.entry_id]

        nxt = copy.deepcopy(current["r"])
        nxt[_OP].update(_rep("Run", "Finish"))
        nxt[_ALARMS] = {
            "x.com.samsung.da.items": [
                {"x.com.samsung.da.code": "DoorA_Opened", "x.com.samsung.da.state": "Created"}
            ]
        }
        current["r"] = nxt
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        cycle = hass.states.get(cycle_id)
        assert cycle is not None
        assert cycle.attributes["event_type"] == CYCLE_FINISHED
        alert = hass.states.get(alert_id)
        assert alert is not None
        assert alert.attributes["event_type"] == ALERT_DOOR
        assert alert.attributes["code"] == "DoorA_Opened"

        # Same reading again: neither entity fires a second time.
        before = (cycle.state, alert.state)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        again = (hass.states.get(cycle_id), hass.states.get(alert_id))
        assert all(s is not None for s in again)
        assert tuple(s.state for s in again if s is not None) == before


async def test_no_event_entities_on_a_fridge(
    hass: HomeAssistant, mock_entry, mock_coordinator_session
) -> None:
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    entries = er.async_entries_for_config_entry(er.async_get(hass), mock_entry.entry_id)
    assert not [e for e in entries if e.domain == "event"]


def test_every_registry_with_a_cycle_gets_events() -> None:
    """Every appliance family whose progress sensor tracks a cycle (FlexDry's
    own registry included) gets the events; nothing else does."""
    from custom_components.localthings.event import EVENT_DEVICE_TYPES, _is_cycle_source
    from custom_components.localthings.registry.by_type import _REGISTRY_BY_KEY
    from custom_components.localthings.registry.discovery import BoundEntity

    with_cycle = set()
    for key, registry in _REGISTRY_BY_KEY.items():
        caps = [c for cs in registry.capabilities.values() for c in cs]
        caps += list(registry.pattern_capabilities)
        for desc in (d for c in caps for d in c.entities):
            if _is_cycle_source(cast(BoundEntity, SimpleNamespace(desc=desc))):
                with_cycle.add(key)
    assert with_cycle == EVENT_DEVICE_TYPES
