"""VS9700 stick-vacuum clean station (issue #478) -- the settings this
station reports beyond the dustbag/dustbin/UV-C surface #131/#219 already
covered: a station light and a Do Not Disturb toggle, plus the AI-mode and
phone-notification hrefs it reports but that carry no home-automation state
(bound to nothing, so no coverage-gap repair fires).
"""

from custom_components.localthings.registry.adapter import flatten
from custom_components.localthings.registry.by_type import for_device_by_oic_type, resolve
from custom_components.localthings.registry.capabilities import vacuum_station
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import SwitchDesc
from tests.conftest import _load_device

FIXTURE = "vacuum_station_vs9700"
DEVICE_TYPES = ("oic.wk.d", "x.com.st.d.stickcleaner")


def _station():
    resources = _load_device(FIXTURE)
    reg = resolve(resources, device_types=DEVICE_TYPES)
    return reg, resources


def _state():
    reg, resources = _station()
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    return flatten(bound, resources)


def test_resolves_via_oic_type():
    reg = for_device_by_oic_type(DEVICE_TYPES)
    assert reg is not None and reg.name == "vacuum_station"


def test_no_unbound_hrefs():
    reg, resources = _station()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_station_light_switch_present_and_writes():
    desc = next(e for e in vacuum_station.LIGHTING.entities if e.key == "station_light")
    assert isinstance(desc, SwitchDesc)
    assert desc.write_fn is not None
    assert desc.write_fn("On", {}) == (["lighting", "vs", "0"], {"x.com.samsung.da.lighting": "On"})
    assert desc.write_fn("Off", {}) == (
        ["lighting", "vs", "0"],
        {"x.com.samsung.da.lighting": "Off"},
    )
    assert _state()["station_light"] is True


def test_do_not_disturb_uses_true_false_string():
    """DND's value field is the string "true"/"false", not the "On"/"Off"
    the rest of the station's switches use. Shares the `dnd` translation key
    with the air-monitor Do Not Disturb switch."""
    desc = next(e for e in vacuum_station.DND.entities if e.key == "dnd")
    assert isinstance(desc, SwitchDesc)
    assert desc.write_fn is not None
    assert desc.write_fn("On", {}) == (["dnd", "vs", "0"], {"x.com.samsung.da.value": "true"})
    assert desc.write_fn("Off", {}) == (["dnd", "vs", "0"], {"x.com.samsung.da.value": "false"})
    assert _state()["dnd"] is False


def test_no_uvc_controls_on_a_station_without_uvc():
    """This station reports uvcSupport "Off" and uvcIntensive "not
    supporting": no UV-C intensive switch (a dead control that wrote to a
    feature the unit lacks) and no permanently-unknown UV-C finished time."""
    state = _state()
    assert "uvc_intensive_mode" not in state
    assert "uvc_finished_time" not in state


def test_uvc_switch_kept_where_the_station_reports_it():
    """The original station (no uvcSupport field, uvcIntensive "Off") keeps
    both, and a stub rep keeps the not-yet-fetched carve-out."""
    from custom_components.localthings.registry.capabilities import vacuum_station as vs

    descs = {d.key: d for d in vs.CLEANSTATION_STATUS.entities}
    resources = _load_device("vacuum_station")
    rep = resources["/status/cleanstation/vs/0"]
    stub = {"href": "/status/cleanstation/vs/0"}
    for key in ("uvc_intensive_mode", "uvc_finished_time"):
        exists = descs[key].exists_fn
        assert exists is not None, key
        assert exists(rep, resources) is True, key
        assert exists(stub, {}) is True, key
    intensive = descs["uvc_intensive_mode"].exists_fn
    assert intensive is not None
    assert intensive({"x.com.samsung.da.uvcIntensive": "On"}, {})
