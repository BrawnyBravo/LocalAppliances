"""Carry a name and area over from Home Assistant's cloud SmartThings
integration when the same appliance is added here.

LocalAppliances addition (not in upstream LocalThings), for people moving
off the cloud integration (docs/moving-from-smartthings.md). Read-only on
the SmartThings side: it only reads that integration's rows in this Home
Assistant's own device registry, and never changes or removes them.

Matching uses what both integrations record about the appliance: its Wi-Fi
MAC (the cloud integration stores it as a network connection) and, failing
that, its serial number. A model alone is never enough -- two identical
washers would be indistinguishable.

The setup step only records which device was chosen (CONF_COPY_FROM);
the copy itself waits for async_apply_copy at entry setup, because this
integration's own device row does not exist until its entities register.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

SMARTTHINGS_DOMAIN = "smartthings"
CONF_COPY_FROM = "copy_from_smartthings_device"

_LOGGER = logging.getLogger(__name__)


def _norm_mac(value: str | None) -> str:
    return "".join(c for c in (value or "").lower() if c in "0123456789abcdef")


def _norm_serial(value: str | None) -> str:
    return (value or "").strip().upper()


@callback
def find_matches(hass: HomeAssistant, serial: str | None, mac: str | None) -> list[dr.DeviceEntry]:
    """SmartThings devices that are the same appliance as (serial, mac)."""
    want_mac = _norm_mac(mac)
    want_serial = _norm_serial(serial)
    if len(want_mac) != 12 and not want_serial:
        return []
    st_entries = {e.entry_id for e in hass.config_entries.async_entries(SMARTTHINGS_DOMAIN)}
    if not st_entries:
        return []
    matches = []
    dev_reg = dr.async_get(hass)
    seen: set[str] = set()
    for st_entry_id in sorted(st_entries):
        for device in dr.async_entries_for_config_entry(dev_reg, st_entry_id):
            if device.id in seen:
                continue
            seen.add(device.id)
            macs = {
                _norm_mac(value)
                for kind, value in device.connections
                if kind == dr.CONNECTION_NETWORK_MAC
            }
            if len(want_mac) == 12 and macs:
                # Both sides know a MAC: it decides. Units can share a serial
                # (issue #381), so a serial match with a different MAC is not one.
                if want_mac in macs:
                    matches.append(device)
            elif want_serial and _norm_serial(device.serial_number) == want_serial:
                matches.append(device)
    return matches


def display_name(device: dr.DeviceEntry) -> str:
    return device.name_by_user or device.name or device.id


@callback
def async_apply_copy(hass: HomeAssistant, entry: ConfigEntry, identifiers) -> None:
    """Copy name and area from the chosen SmartThings device onto this
    entry's device, then forget the choice so it runs once.

    Leaves anything the user already set here alone: a name or area given
    to the new device between setup and now wins.
    """
    source_id = entry.data.get(CONF_COPY_FROM)
    if not source_id:
        return
    dev_reg = dr.async_get(hass)
    source = dev_reg.async_get(source_id)
    target = next(
        (
            d
            for d in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
            if set(identifiers) & d.identifiers
        ),
        None,
    )
    if target is None:
        # Entities have not registered yet (an offline first load); try again
        # on the next setup rather than dropping the choice.
        return
    # Older registries can merge rows that share a MAC across integrations;
    # then there is nothing to copy, and writing would change SmartThings'.
    if source is not None and source.id != target.id:
        name = None if target.name_by_user else (source.name_by_user or source.name)
        area_id = None if target.area_id else source.area_id
        if name or area_id:
            dev_reg.async_update_device(
                target.id,
                name_by_user=name or target.name_by_user,
                area_id=area_id or target.area_id,
            )
            copied = [label for label, v in (("area_id", area_id), ("name_by_user", name)) if v]
            _LOGGER.info("Copied %s from the SmartThings device", ", ".join(copied))
    data = {k: v for k, v in entry.data.items() if k != CONF_COPY_FROM}
    hass.config_entries.async_update_entry(entry, data=data)
