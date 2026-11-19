"""Event platform for Local Things: cycle and alert events for laundry and
dishwashers.

LocalAppliances addition (not in upstream LocalThings). Nothing new is read
from the appliance: each event is an edge in a value the sensors already
show, so an automation can trigger on "the wash finished" or "a new alarm
appeared" instead of watching a sensor's state change and guessing which
change counts.

- Cycle: `started` / `finished`, taken from the same tests the progress
  sensor's #345 hold uses (operational._just_finished and
  _new_cycle_running), so "finished" still fires on the boards whose
  `state` reads idle before `progress` reads Finish. CycleTracker keeps
  each to once per cycle: a pause and resume is not a new start, a
  `progress` stuck at (or flapping back to) Finish is not a second finish,
  and a delayed start fires `started` when the cycle itself begins, not
  when the delay is set.
- Alert: `door_open` / `alarm`, one per alarm code that newly appears in
  /alarms/vs/0 (common._active_alarm_codes). Codes containing "door" are
  door alarms (a dishwasher's DoorA_Opened); any other code is an alarm
  (an error code, or a notice such as a dishwasher's SNSF_Reached),
  with the code itself in the event's `code` attribute.

The first reading after setup only seeds the previous value: an appliance
that is already finished, or already alarming, when Home Assistant starts
does not fire.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LocalThingsCoordinator
from .entity import async_add_bound_entities
from .registry.adapter import _key
from .registry.discovery import BoundEntity
from .registry.entities import SensorDesc

# Device types that run a cycle a person waits on. Ovens share the same
# operational href, but "finished" there is not a moment anyone asked for.
# FlexDry boards resolve to their own "flexdry" registry, a dryer all the same.
EVENT_DEVICE_TYPES = frozenset({"washer", "dryer", "flexdry", "dishwasher", "air_dresser"})

CYCLE_STARTED = "started"
CYCLE_FINISHED = "finished"
ALERT_DOOR = "door_open"
ALERT_ALARM = "alarm"


class CycleTracker:
    """One appliance's cycle, reading by reading.

    `desc` is the bound `progress` SensorDesc: its sticky_fn says "reads
    Finish" and its sticky_bypass_fn says "a new cycle is genuinely running".
    The first reading only seeds: an appliance already running, paused or
    finished when Home Assistant starts fires nothing until it moves on.
    """

    def __init__(self, desc: SensorDesc) -> None:
        assert desc.sticky_fn is not None and desc.sticky_bypass_fn is not None
        self._finished_fn = desc.sticky_fn
        self._running_fn = desc.sticky_bypass_fn
        self._seeded = False
        self._was_finished = False
        # Between a start and its finish, pauses included.
        self._in_cycle = False

    def update(self, rep: dict) -> str | None:
        finished = bool(self._finished_fn(rep))
        progress = str(rep.get("x.com.samsung.da.progress") or "None")
        # A delay counts down with state Run (washers report progress
        # Delaywash), but nothing is washing yet.
        running = bool(self._running_fn(rep)) and "delay" not in progress.lower()
        state = rep.get("x.com.samsung.da.state")
        paused = state in ("Pause", "Paused")
        # Idle with progress reset: the cycle ended without a Finish (stopped
        # or cancelled). Idle alone is not enough -- #345's washer reads idle
        # just before its Finish arrives.
        reset = not running and not paused and not finished and progress == "None"

        if not self._seeded:
            self._seeded = True
            self._was_finished = finished
            self._in_cycle = running or paused
            return None

        event = None
        if running and not self._in_cycle:
            self._in_cycle = True
            event = CYCLE_STARTED
        elif finished and not self._was_finished and self._in_cycle:
            self._in_cycle = False
            event = CYCLE_FINISHED
        elif reset:
            self._in_cycle = False
        self._was_finished = finished
        return event


def alarm_codes(value) -> frozenset[str]:
    """The `alarm_code` sensor's joined value -> its set of active codes."""
    if not isinstance(value, str) or value in ("", "none"):
        return frozenset()
    return frozenset(c.strip() for c in value.split(",") if c.strip())


def new_alerts(previous: frozenset[str] | None, current: frozenset[str]):
    """[(event_type, code)] for codes in `current` that `previous` lacked,
    in a stable order. None for `previous` seeds without firing."""
    if previous is None:
        return []
    return [
        (ALERT_DOOR if "door" in code.lower() else ALERT_ALARM, code)
        for code in sorted(current - previous)
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LocalThingsCoordinator = hass.data[DOMAIN][entry.entry_id]

    def select(b: BoundEntity) -> bool:
        # Read at each discovery, so a type resolved only by a later read
        # still gets its events without a reload.
        if coordinator.device_type_name not in EVENT_DEVICE_TYPES:
            return False
        return _is_cycle_source(b) or b.desc.key == "alarm_code"

    def factory(b: BoundEntity) -> EventEntity:
        if _is_cycle_source(b):
            return LocalThingsCycleEvent(coordinator, b)
        return LocalThingsAlertEvent(coordinator, b)

    # The shared adder brings in sources a later discovery binds and rebinds
    # one whose href moves (#807), like every other platform.
    async_add_bound_entities(entry, coordinator, async_add_entities, select, factory)


def _is_cycle_source(b: BoundEntity) -> bool:
    desc = b.desc
    return (
        isinstance(desc, SensorDesc)
        and desc.key == "progress"
        and desc.sticky_fn is not None
        and desc.sticky_bypass_fn is not None
    )


class _LocalThingsEvent(CoordinatorEntity[LocalThingsCoordinator], EventEntity):
    """Shares the bound sensor's device and subdevice; own unique_id."""

    _attr_has_entity_name = True
    _suffix: str

    def __init__(self, coordinator: LocalThingsCoordinator, bound: BoundEntity) -> None:
        super().__init__(coordinator)
        self._bound = bound
        self._source_key = _key(bound)
        # The source sensor's own key (subdevice prefix and instance included)
        # keeps two bound instances from colliding.
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.device_key}_{self._source_key}_{self._suffix}_event"
        )
        self._attr_translation_key = self._suffix

    @property
    def device_info(self):
        return self.coordinator.device_info_for(self._bound.subdevice)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Seed from whatever is already cached, so a reload never fires.
        if self.coordinator.data is not None:
            self._evaluate(fire=False)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._evaluate(fire=True)
        super()._handle_coordinator_update()

    def _evaluate(self, *, fire: bool) -> None:
        raise NotImplementedError


class LocalThingsCycleEvent(_LocalThingsEvent):
    _suffix = "cycle"
    _attr_icon = "mdi:washing-machine"

    def __init__(self, coordinator: LocalThingsCoordinator, bound: BoundEntity) -> None:
        super().__init__(coordinator, bound)
        self._attr_event_types = [CYCLE_STARTED, CYCLE_FINISHED]
        desc = bound.desc
        assert isinstance(desc, SensorDesc)
        self._tracker = CycleTracker(desc)

    def _evaluate(self, *, fire: bool) -> None:
        rep = self.coordinator.resource(self._bound.href)
        if not rep:
            return
        event = self._tracker.update(rep)
        if fire and event is not None:
            self._trigger_event(event)


class LocalThingsAlertEvent(_LocalThingsEvent):
    _suffix = "alert"
    _attr_icon = "mdi:alert"

    def __init__(self, coordinator: LocalThingsCoordinator, bound: BoundEntity) -> None:
        super().__init__(coordinator, bound)
        self._attr_event_types = [ALERT_DOOR, ALERT_ALARM]
        self._codes: frozenset[str] | None = None

    def _evaluate(self, *, fire: bool) -> None:
        value = (self.coordinator.data or {}).get(self._source_key)
        if value is None:
            return
        current = alarm_codes(value)
        alerts = new_alerts(self._codes, current)
        self._codes = current
        if fire:
            # One write per event: the entity's state holds only the last
            # one, so two codes in one poll would otherwise reach automations
            # as a single event.
            for event_type, code in alerts:
                self._trigger_event(event_type, {"code": code})
                self.async_write_ha_state()
