"""A UUID-prefixed subdevice's identity does not depend on the letter case
its UUID arrived in (review L3), and an install registered under another
case is moved onto it rather than duplicated."""

from __future__ import annotations

import importlib
import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.localthings.const import DOMAIN
from custom_components.localthings.entity import async_migrate_subdevice_case
from custom_components.localthings.registry.adapter import _key
from custom_components.localthings.registry.subdevices import (
    Subdevice,
    enumerate_subdevices,
    normalize_seed_batch,
)
from tests.conftest import _load_device_full
from tests.test_subdevice_discovery import _coordinator, _discover_with
from tests.test_subdevices import _DEVCOL_REP, _FakeSession

_UUID = "6c2dff6d-ee5c-dad1-6a5e-000000000001"
_UPPER = _UUID.upper()
_FIXTURE = "airconditioner_fac_bora_2in1"


# ---------------------------------------------------------------------------
# Subdevice itself
# ---------------------------------------------------------------------------


def test_identity_is_lowercase_but_the_wire_keeps_the_devices_spelling():
    upper = Subdevice(kind="prefixed", key=_UPPER, seed_path=(_UPPER, "device", "0"))
    lower = Subdevice(kind="prefixed", key=_UUID, seed_path=(_UUID, "device", "0"))

    assert upper.key == lower.key == _UUID
    assert upper.key_prefix == lower.key_prefix
    # A CoAP path is case-sensitive: what is sent stays as the device spelled it.
    assert upper.to_actual("/mode/vs/0") == f"/{_UPPER}/mode/vs/0"
    assert lower.to_actual("/mode/vs/0") == f"/{_UUID}/mode/vs/0"


def test_a_flat_subdevice_keeps_its_wire_spelling_too():
    flat = Subdevice(kind="prefixed", key=_UPPER, seed_path=(), wire_key=_UPPER)
    assert flat.key == _UUID
    assert flat.to_actual("/mode/vs/0") == f"/{_UPPER}/mode/vs/0"


@pytest.mark.parametrize("spelling", [_UUID, _UPPER])
def test_either_spelling_maps_back_to_the_canonical_href(spelling):
    subdevice = Subdevice(kind="prefixed", key=_UUID, seed_path=(_UUID, "device", "0"))
    assert subdevice.to_canonical(f"/{spelling}/mode/vs/0") == "/mode/vs/0"
    assert subdevice.owns(f"/{spelling}/mode/vs/0")


def test_a_seed_batch_in_either_case_is_not_prefixed_twice():
    subdevice = Subdevice(kind="prefixed", key=_UPPER, seed_path=(_UPPER, "device", "0"))
    batch = {f"/{_UUID}/mode/vs/0": {"m": 1}, "/power/vs/0": {"p": 1}}
    assert normalize_seed_batch(subdevice, batch) == {
        f"/{_UUID}/mode/vs/0": {"m": 1},
        f"/{_UPPER}/power/vs/0": {"p": 1},
    }


def test_the_key_does_not_depend_on_which_source_named_the_uuid():
    """subdeviceIdList (upper) one start, only the /oic/res link (lower) the
    next, when /subdevices/vs/0 came back as a stub: same key both times."""

    seeds = {
        (spelling, "device", "0"): [_DEVCOL_REP, {"href": "/mode/vs/0", "rep": {"m": 1}}]
        for spelling in (_UUID, _UPPER)
    }

    from_list, _ = enumerate_subdevices(
        _FakeSession(seeds),
        {"/subdevices/vs/0": {"x.com.samsung.da.subdeviceIdList": [_UPPER]}},
        [],
    )
    from_link, _ = enumerate_subdevices(
        _FakeSession(seeds),
        {"/subdevices/vs/0": {"href": "/subdevices/vs/0"}},
        [
            {
                "di": "a",
                "links": [
                    {"href": f"/{_UUID}/multidevice/vs/0", "rt": ["x.com.samsung.da.multidevice"]}
                ],
            }
        ],
    )
    prefixed_list = [su for su in from_list if su.kind == "prefixed"]
    prefixed_link = [su for su in from_link if su.kind == "prefixed"]
    assert prefixed_list and prefixed_link
    assert prefixed_list[0].key == prefixed_link[0].key == _UUID
    assert prefixed_list[0].key_prefix == prefixed_link[0].key_prefix


# ---------------------------------------------------------------------------
# Upgrade: no orphaned or duplicate entities
# ---------------------------------------------------------------------------


def _fixture(upper: bool):
    resources, oic_res, seeds = _load_device_full(_FIXTURE)
    if not upper:
        return resources, oic_res, seeds
    # The same appliance, reporting its subdevice UUID in capitals everywhere.
    blob = json.dumps([resources, oic_res, seeds]).replace(_UUID, _UPPER)
    assert _UPPER in blob
    resources, oic_res, seeds = json.loads(blob)
    return resources, oic_res, seeds


async def _discovered(hass: HomeAssistant, upper: bool):
    coordinator = _coordinator(hass)
    await _discover_with(coordinator, *_fixture(upper))
    return coordinator


def _sub_unique_ids(coordinator) -> set[str]:
    return {
        f"{DOMAIN}_{coordinator.device_key}_{_key(b)}"
        for b in coordinator.bound
        if b.subdevice.kind == "prefixed"
    }


async def test_an_upper_case_device_gets_the_same_ids_as_a_lower_case_one(hass):
    lower = await _discovered(hass, upper=False)
    upper_ids = _sub_unique_ids(await _discovered(hass, upper=True))
    assert upper_ids
    assert upper_ids == _sub_unique_ids(lower)
    sub = next(b for b in lower.bound if b.subdevice.kind == "prefixed")
    assert sub.subdevice.key == _UUID


async def test_an_install_registered_in_capitals_is_moved_not_duplicated(hass):
    """The install as an older release left it: every subdevice entity and
    the subdevice's device registered under the capitalized UUID."""
    coordinator = await _discovered(hass, upper=True)
    entry = coordinator._entry
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    old_ident = (DOMAIN, f"{coordinator.device_key}_{_UPPER}")
    device = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, identifiers={old_ident})
    old_slug = "subdevice_" + _UPPER.replace("-", "") + "_"
    new_slug = "subdevice_" + _UUID.replace("-", "") + "_"
    expected = _sub_unique_ids(coordinator)
    before = {}
    for uid in expected:
        old_uid = uid.replace(new_slug, old_slug)
        assert old_uid != uid
        ent = ent_reg.async_get_or_create(
            "sensor", DOMAIN, old_uid, config_entry=entry, device_id=device.id
        )
        before[uid] = ent.entity_id
    # A master entity, which must be left exactly as it is.
    master = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{DOMAIN}_{coordinator.device_key}_power", config_entry=entry
    )

    async_migrate_subdevice_case(hass, entry, coordinator)
    async_migrate_subdevice_case(hass, entry, coordinator)  # idempotent

    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    assert len(entries) == len(expected) + 1  # nothing created, nothing lost
    for uid, entity_id in before.items():
        assert ent_reg.async_get_entity_id("sensor", DOMAIN, uid) == entity_id
    assert ent_reg.async_get(master.entity_id).unique_id == master.unique_id

    new_ident = (DOMAIN, f"{coordinator.device_key}_{_UUID}")
    assert coordinator.device_info_for(coordinator.subdevices[0])["identifiers"] == {new_ident}
    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert [d.id for d in devices] == [device.id]
    assert new_ident in devices[0].identifiers
    assert old_ident not in devices[0].identifiers


async def test_a_lower_case_install_is_untouched(hass):
    coordinator = await _discovered(hass, upper=False)
    entry = coordinator._entry
    ent_reg = er.async_get(hass)
    uid = next(iter(_sub_unique_ids(coordinator)))
    ent = ent_reg.async_get_or_create("sensor", DOMAIN, uid, config_entry=entry)

    async_migrate_subdevice_case(hass, entry, coordinator)

    assert ent_reg.async_get(ent.entity_id).unique_id == uid
    assert len(er.async_entries_for_config_entry(ent_reg, entry.entry_id)) == 1


async def test_both_spellings_already_registered_are_both_left_alone(hass, caplog):
    coordinator = await _discovered(hass, upper=False)
    entry = coordinator._entry
    ent_reg = er.async_get(hass)
    uid = next(iter(_sub_unique_ids(coordinator)))
    old_uid = uid.replace(_UUID.replace("-", ""), _UPPER.replace("-", ""))
    new = ent_reg.async_get_or_create("sensor", DOMAIN, uid, config_entry=entry)
    old = ent_reg.async_get_or_create("sensor", DOMAIN, old_uid, config_entry=entry)

    async_migrate_subdevice_case(hass, entry, coordinator)

    assert ent_reg.async_get(new.entity_id).unique_id == uid
    assert ent_reg.async_get(old.entity_id).unique_id == old_uid
    assert "two spellings" in caplog.text


@pytest.mark.parametrize(
    "platform",
    [
        "binary_sensor",
        "button",
        "climate",
        "fan",
        "light",
        "number",
        "select",
        "sensor",
        "switch",
        "time",
        "water_heater",
    ],
)
async def test_every_platform_migrates_before_adding_entities(hass, monkeypatch, platform):
    """Each platform registers its own entities, so each has to move them
    before adding any -- otherwise HA creates fresh ones beside the old."""
    module = importlib.import_module(f"custom_components.localthings.{platform}")
    coordinator = await _discovered(hass, upper=False)
    hass.data.setdefault(DOMAIN, {})[coordinator._entry.entry_id] = coordinator
    calls: list[str] = []
    monkeypatch.setattr(
        module, "async_migrate_subdevice_case", lambda *args: calls.append("migrate")
    )

    def _add(entities, *args, **kwargs):
        list(entities)
        calls.append("add")

    await module.async_setup_entry(hass, coordinator._entry, _add)

    assert calls and calls[0] == "migrate"
