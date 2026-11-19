"""Copying a name and area from the cloud SmartThings integration's device
when the same appliance is added here (LocalAppliances addition)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import CONF_HOST, DOMAIN
from custom_components.localthings.smartthings_copy import CONF_COPY_FROM, find_matches

from .conftest import ENTRY_DATA, MOCK_DEVICE_KEY, MOCK_HOST, MOCK_MAC, MOCK_SERIAL


def _smartthings_device(hass: HomeAssistant, **kwargs) -> dr.DeviceEntry:
    st_entry = MockConfigEntry(domain="smartthings", data={})
    st_entry.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=st_entry.entry_id,
        identifiers={("smartthings", "sample-cloud-id")},
        name="Sample Fridge",
        **kwargs,
    )


async def test_matches_by_mac_in_any_format(hass: HomeAssistant) -> None:
    device = _smartthings_device(
        hass, connections={(dr.CONNECTION_NETWORK_MAC, MOCK_MAC.upper().replace(":", "-"))}
    )
    assert [d.id for d in find_matches(hass, None, MOCK_MAC)] == [device.id]


async def test_matches_by_serial(hass: HomeAssistant) -> None:
    device = _smartthings_device(hass, serial_number=MOCK_SERIAL.lower())
    assert [d.id for d in find_matches(hass, MOCK_SERIAL, None)] == [device.id]


async def test_same_serial_different_mac_is_not_a_match(hass: HomeAssistant) -> None:
    _smartthings_device(
        hass,
        serial_number=MOCK_SERIAL,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:00:09:09")},
    )
    assert find_matches(hass, MOCK_SERIAL, MOCK_MAC) == []


async def test_no_match_on_model_alone_or_other_integrations(hass: HomeAssistant) -> None:
    _smartthings_device(hass, model="TEST-MODEL", serial_number="OTHER-SERIAL")
    other = MockConfigEntry(domain="other_integration", data={})
    other.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("other_integration", "x")},
        connections={(dr.CONNECTION_NETWORK_MAC, MOCK_MAC)},
    )
    assert find_matches(hass, MOCK_SERIAL, MOCK_MAC) == []
    assert find_matches(hass, None, None) == []


async def _run_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: MOCK_HOST})


async def test_flow_offers_the_copy_and_records_the_choice(hass: HomeAssistant, mock_probe) -> None:
    device = _smartthings_device(hass, connections={(dr.CONNECTION_NETWORK_MAC, MOCK_MAC)})
    result = await _run_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "smartthings_copy"
    assert result["description_placeholders"] == {"name": "Sample Fridge"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"copy": True, CONF_COPY_FROM: device.id}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_COPY_FROM] == device.id


async def test_flow_declined_stores_nothing(hass: HomeAssistant, mock_probe) -> None:
    device = _smartthings_device(hass, connections={(dr.CONNECTION_NETWORK_MAC, MOCK_MAC)})
    result = await _run_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"copy": False, CONF_COPY_FROM: device.id}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_COPY_FROM not in result["data"]


async def test_flow_without_smartthings_skips_the_step(hass: HomeAssistant, mock_probe) -> None:
    result = await _run_flow(hass)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_COPY_FROM not in result["data"]


async def test_setup_copies_name_and_area_once(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    area = ar.async_get(hass).async_create("Sample Area")
    source = _smartthings_device(hass, connections={(dr.CONNECTION_NETWORK_MAC, MOCK_MAC)})
    dev_reg = dr.async_get(hass)
    dev_reg.async_update_device(source.id, area_id=area.id, name_by_user="Sample Name")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, CONF_COPY_FROM: source.id},
        unique_id=f"localthings_{MOCK_DEVICE_KEY}",
        version=4,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    ours = [
        d
        for d in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        if d.via_device_id is None
    ]
    assert len(ours) == 1
    assert ours[0].name_by_user == "Sample Name"
    assert ours[0].area_id == area.id
    assert CONF_COPY_FROM not in entry.data
    # The SmartThings row is left exactly as it was.
    untouched = dev_reg.async_get(source.id)
    assert untouched is not None
    assert untouched.name_by_user == "Sample Name"
    assert untouched.area_id == area.id
    assert untouched.config_entries == source.config_entries
