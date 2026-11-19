"""The shipped blueprints parse and validate as automation blueprints
(LocalAppliances addition)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.util.yaml import load_yaml

BLUEPRINTS = Path(__file__).resolve().parents[2] / "blueprints" / "automation" / "localappliances"


@pytest.mark.parametrize("path", sorted(BLUEPRINTS.glob("*.yaml")), ids=lambda p: p.name)
def test_blueprint_is_valid(path: Path) -> None:
    blueprint = Blueprint(
        cast(dict, load_yaml(str(path))), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.domain == "automation"
    assert "not affiliated" in blueprint.metadata["description"]
    assert set(blueprint.inputs)


def test_blueprints_exist() -> None:
    assert len(list(BLUEPRINTS.glob("*.yaml"))) == 2


@pytest.mark.parametrize("path", sorted(BLUEPRINTS.glob("*.yaml")), ids=lambda p: p.name)
async def test_blueprint_builds_a_valid_automation(hass, path: Path) -> None:
    """Filled in with sample inputs, each blueprint is an automation Home
    Assistant accepts -- catches a wrong trigger or condition key that the
    blueprint schema alone does not look at."""
    from homeassistant.components.automation.config import async_validate_config_item
    from homeassistant.components.blueprint.models import BlueprintInputs
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    blueprint = Blueprint(
        cast(dict, load_yaml(str(path))), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    inputs = {
        name: (
            [{"action": "persistent_notification.create", "data": {"message": "x"}}]
            if name.endswith("actions")
            else "event.sample_appliance"
        )
        for name, spec in blueprint.inputs.items()
        if (spec or {}).get("default") is None
    }
    config = BlueprintInputs(blueprint, {"use_blueprint": {"path": path.name, "input": inputs}})
    substituted = {"id": "sample", **config.async_substitute()}
    validated = await async_validate_config_item(hass, "sample", substituted)
    assert validated is not None
    assert getattr(validated, "validation_error", None) is None


@pytest.mark.parametrize("path", sorted(BLUEPRINTS.glob("*.yaml")), ids=lambda p: p.name)
def test_blueprint_ignores_attribute_only_changes(path: Path) -> None:
    """A rename or icon change rewrites the event entity's state with the same
    timestamp; only a new event (a new timestamp) may run the actions."""
    assert "trigger.from_state.state != trigger.to_state.state" in path.read_text(encoding="utf-8")
