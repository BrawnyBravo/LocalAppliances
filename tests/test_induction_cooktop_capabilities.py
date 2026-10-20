"""Tests for the TP1X_DA-KS-COOKTOP induction boards (issue #86), which share
the cooktop registry with the /mode/vs/0 options-array boards."""

from custom_components.localthings.registry.adapter import flatten
from custom_components.localthings.registry.by_type import cooktop, for_device_by_model
from custom_components.localthings.registry.discovery import discover
from tests.conftest import _load_device


def _cooktop(name="induction_cooktop"):
    resources = _load_device(name)
    info = resources["/information/vs/0"]
    reg = for_device_by_model(
        info["x.com.samsung.da.modelNum"],
        info["x.com.samsung.da.description"],
    )
    return reg, resources


def _state(name="induction_cooktop"):
    reg, resources = _cooktop(name)
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    return flatten(bound, resources)


def test_model_resolves_to_cooktop_registry():
    reg, _ = _cooktop()
    assert reg is not None and reg.name == "cooktop"
    assert reg is cooktop.REGISTRY


def test_no_unbound_hrefs():
    """Every resource in the issue #86 dump binds or is ignored -- clears
    the coverage-gap repair."""
    reg, resources = _cooktop()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_expected_entities_present():
    state = _state()
    for key in (
        "cooktop_state",
        "cooktop_power",
        "cooktop_child_lock",
        "burner_0_power_level",
        "burner_0_state",
        "burner_0_hot_surface",
        "burner_0_pan_detected",
        "burner_2_pan_detected",
        "paired_hood_connected",
        "probe_connected",
        "probe_temperature",
        "energy_kwh",
        "alarm_code",
    ):
        assert key in state, key


def test_unreported_burners_gated_out():
    """Dump reports numberOfBurners=3 (indices 0-2) -- burner slot 3+ of
    range.MAX_BURNERS must not appear as entities."""
    state = _state()
    assert "burner_3_power_level" not in state


def test_recipe_status_href_is_ignored_not_unbound():
    """/cooktop/recipe/status/vs/0 is idle/empty on this dump -- covered by
    ignored.py, not modeled as an entity (same treatment as the microwave
    family's /recipe/cook/vs/0)."""
    reg, _ = _cooktop()
    ignored_hrefs = {
        cap.href for caps in reg.capabilities.values() for cap in caps if cap.entities == ()
    }
    assert "/cooktop/recipe/status/vs/0" in ignored_hrefs


def test_nv9000d_resolves_with_complete_coverage():
    """NV9000D-/KO2 reuses the standalone induction-cooktop surface but
    omits the optional Bluetooth probe and paired-hood resources while adding
    the read-only hot-surface auto-shutoff status."""
    reg, resources = _cooktop("induction_cooktop_nv9000d")
    assert reg is cooktop.REGISTRY

    unbound = []
    discover(
        resources,
        reg.capabilities,
        reg.pattern_capabilities,
        log=unbound.append,
    )
    assert unbound == []

    state = _state("induction_cooktop_nv9000d")
    assert state["cooktop_safety_shutoff_enabled"] is True
    assert not any(key.startswith(("probe_", "paired_hood_")) for key in state)


def _bound_burner_status_descs(name):
    from custom_components.localthings.registry.entities import SelectDesc

    reg, resources = _cooktop(name)
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    descs = [b.desc for b in bound if b.href == "/cooktop/status/vs/0"]
    return descs, SelectDesc


def test_standalone_cooktop_power_level_is_read_only():
    """cooktop.py's rule: a cooktop must not be remotely ignited by an
    automation. The range combo's burner power-level select (options include
    boost and keepWarm) used to bind here too; on a standalone cooktop it is
    a read-only sensor under the same key."""
    from custom_components.localthings.registry.entities import SensorDesc

    for name in ("induction_cooktop", "induction_cooktop_nv9000d"):
        descs, select_desc = _bound_burner_status_descs(name)
        power = [d for d in descs if d.key.endswith("_power_level")]
        assert power, name
        assert all(isinstance(d, SensorDesc) for d in power), name
        assert not [d for d in descs if isinstance(d, select_desc)], name
        # The only writable control left on the burner surface is the lock.
        writable = sorted(d.key for d in descs if getattr(d, "write_fn", None) is not None)
        assert writable == ["cooktop_child_lock"], name


def test_standalone_cooktop_power_level_reads_the_burner():
    state = _state()
    assert state["burner_0_power_level"] is not None
    assert "burner_3_power_level" not in state
