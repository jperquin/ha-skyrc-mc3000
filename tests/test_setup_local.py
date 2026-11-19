"""Integration ownership and failed-setup cleanup, without Home Assistant."""

from __future__ import annotations

import asyncio
from enum import Enum
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "custom_components" / "skyrc_mc3000"
DOMAIN = "skyrc_mc3000"


class ConfigEntryError(Exception):
    pass


class HomeAssistantError(Exception):
    pass


class Platform(Enum):
    SENSOR = "sensor"
    SELECT = "select"
    BUTTON = "button"
    SWITCH = "switch"
    NUMBER = "number"


class Services:
    def __init__(self):
        self.handlers = {("light", "turn_on"): object()}
        self.removed = []

    def async_register(self, domain, name, handler, **kwargs):
        self.handlers[(domain, name)] = handler

    def async_remove(self, domain, name):
        self.removed.append((domain, name))
        self.handlers.pop((domain, name), None)


class ConfigEntries:
    def __init__(self):
        self.forwards = []
        self.unloads = []
        self.forward_error = None
        self.unload_result = True

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwards.append((entry.entry_id, tuple(platforms)))
        if self.forward_error is not None:
            raise self.forward_error

    async def async_unload_platforms(self, entry, platforms):
        self.unloads.append((entry.entry_id, tuple(platforms)))
        return self.unload_result


class Bus:
    def __init__(self):
        self.listeners = []

    def async_listen_once(self, event, callback):
        record = (event, callback)
        self.listeners.append(record)
        return lambda: self.listeners.remove(record)


class Entry:
    def __init__(self, identifier):
        self.entry_id = identifier
        self.data = {"address": "FAKE-" + identifier}
        self.unload_callbacks = []

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)


class Coordinator:
    def __init__(self, hass, address):
        self.hass, self.address = hass, address
        self.quality = None
        self.close_count = 0

    async def async_refresh(self):
        pass

    async def async_close(self):
        self.close_count += 1


class Quality:
    def __init__(self):
        self.close_count = 0

    async def async_close(self):
        self.close_count += 1


class Telemetry:
    async def async_load(self):
        pass


@pytest.fixture
def setup_environment():
    package_name = "mc3000_setup_under_test"
    created, installed_filters, removed_filters = [], [], []
    state = SimpleNamespace(fail_programs=False, fail_quality=False)
    hass = SimpleNamespace(
        data={},
        services=Services(),
        config_entries=ConfigEntries(),
        bus=Bus(),
        scheduled=[],
    )

    def schedule(coroutine):
        # Ownership tests check that polling is scheduled. No real background
        # poll is needed, and closing the inert fake coroutine avoids a leak.
        hass.scheduled.append(coroutine.cr_code.co_name)
        coroutine.close()

    hass.async_create_task = schedule

    def make_coordinator(hass, address):
        coordinator = Coordinator(hass, address)
        created.append(coordinator)
        return coordinator

    def install_filter():
        token = object()
        installed_filters.append(token)
        return token

    async def setup_programs(hass, entry, coordinator):
        for name in (
            "save_profile",
            "delete_profile",
            "select_profile",
            "apply_profile",
        ):
            hass.services.async_register(DOMAIN, name, object())
        if state.fail_programs:
            raise RuntimeError("profile storage failed")
        return SimpleNamespace()

    quality_services = ("save_cell", "start_quality_test")

    async def setup_quality(hass, entry, coordinator):
        coordinator.quality = Quality()
        for name in quality_services:
            hass.services.async_register(DOMAIN, name, object())
        if state.fail_quality:
            raise RuntimeError("quality storage failed")
        return coordinator.quality

    stubs = {}
    for name in (
        "homeassistant",
        "homeassistant.const",
        "homeassistant.exceptions",
        f"{package_name}.const",
        f"{package_name}.logging_utils",
        f"{package_name}.program_validation",
        f"{package_name}.programs",
        f"{package_name}.quality",
        f"{package_name}.telemetry",
        f"{package_name}.coordinator",
    ):
        stubs[name] = ModuleType(name)
    stubs["homeassistant.const"].Platform = Platform
    stubs["homeassistant.exceptions"].ConfigEntryError = ConfigEntryError
    stubs["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    stubs[f"{package_name}.const"].DOMAIN = DOMAIN
    stubs[f"{package_name}.const"].CONF_ADDRESS = "address"
    stubs[f"{package_name}.logging_utils"].install_library_log_filter = install_filter
    stubs[
        f"{package_name}.logging_utils"
    ].remove_library_log_filter = removed_filters.append
    stubs[f"{package_name}.program_validation"].validate_program = dict
    stubs[f"{package_name}.program_validation"].CHEMISTRY_CODES = {"liion": 0}
    stubs[f"{package_name}.program_validation"].NUMBERS = {
        "charge_current": (0.05, 3, 0.01)
    }
    stubs[f"{package_name}.programs"].async_setup_programs = setup_programs
    stubs[f"{package_name}.quality"].async_setup_quality = setup_quality
    stubs[f"{package_name}.quality"].SERVICE_NAMES = quality_services
    stubs[f"{package_name}.telemetry"].create = lambda hass, entry: Telemetry()
    stubs[f"{package_name}.coordinator"].SkyrcMc3000Coordinator = make_coordinator

    spec = importlib.util.spec_from_file_location(
        package_name, SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)]
    )
    module = importlib.util.module_from_spec(spec)
    stubs[package_name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
        yield SimpleNamespace(
            module=module,
            hass=hass,
            state=state,
            created=created,
            installed_filters=installed_filters,
            removed_filters=removed_filters,
            first=Entry("first"),
            second=Entry("second"),
        )


def test_manifest_advertises_single_config_entry():
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["single_config_entry"] is True


@pytest.mark.asyncio
async def test_second_setup_cannot_replace_first_charger_or_service_handlers(
    setup_environment,
):
    e = setup_environment
    assert await e.module.async_setup_entry(e.hass, e.first) is True
    owner_data = dict(e.hass.data[DOMAIN])
    handlers = dict(e.hass.services.handlers)

    with pytest.raises(ConfigEntryError, match="Only one MC3000"):
        await e.module.async_setup_entry(e.hass, e.second)

    assert e.hass.data[DOMAIN] == owner_data
    assert e.hass.services.handlers == handlers
    assert len(e.created) == len(e.installed_filters) == 1
    assert e.created[0].close_count == 0
    assert e.hass.scheduled == ["async_refresh"]
    assert len(e.hass.config_entries.forwards) == 1


@pytest.mark.asyncio
async def test_unloading_rejected_entry_does_not_touch_owner(setup_environment):
    e = setup_environment
    await e.module.async_setup_entry(e.hass, e.first)
    handlers = dict(e.hass.services.handlers)
    with pytest.raises(ConfigEntryError):
        await e.module.async_setup_entry(e.hass, e.second)

    assert await e.module.async_unload_entry(e.hass, e.second) is True
    assert e.hass.data[DOMAIN]["entry_id"] == "first"
    assert e.hass.services.handlers == handlers
    assert e.hass.services.removed == []
    assert e.hass.config_entries.unloads == []
    assert e.created[0].close_count == e.created[0].quality.close_count == 0
    assert e.removed_filters == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_stage", ["programs", "quality", "platforms", "cancellation"]
)
async def test_failed_setup_releases_owned_resources_and_can_retry(
    setup_environment, failure_stage
):
    e = setup_environment
    e.state.fail_programs = failure_stage == "programs"
    e.state.fail_quality = failure_stage == "quality"
    if failure_stage == "platforms":
        e.hass.config_entries.forward_error = RuntimeError("platform setup failed")
    elif failure_stage == "cancellation":
        e.hass.config_entries.forward_error = asyncio.CancelledError()

    expected = (
        asyncio.CancelledError if failure_stage == "cancellation" else RuntimeError
    )
    with pytest.raises(expected):
        await e.module.async_setup_entry(e.hass, e.first)

    failed = e.created[0]
    assert e.hass.data[DOMAIN] == {}
    assert failed.close_count == 1
    if failed.quality is not None:
        assert failed.quality.close_count == 1
    assert set(e.hass.services.handlers) == {("light", "turn_on")}
    assert e.removed_filters == e.installed_filters

    e.state.fail_programs = e.state.fail_quality = False
    e.hass.config_entries.forward_error = None
    assert await e.module.async_setup_entry(e.hass, e.first) is True
    assert e.hass.data[DOMAIN]["entry_id"] == "first"
    assert e.hass.data[DOMAIN]["coordinator"] is e.created[1]
    assert e.created[1].close_count == 0
    assert (DOMAIN, "start_slot") in e.hass.services.handlers


@pytest.mark.asyncio
async def test_successful_unload_releases_owner_and_all_owned_services(
    setup_environment,
):
    e = setup_environment
    await e.module.async_setup_entry(e.hass, e.first)
    coordinator = e.created[0]
    assert await e.module.async_unload_entry(e.hass, e.first) is True
    assert coordinator.close_count == coordinator.quality.close_count == 1
    assert e.hass.data[DOMAIN] == {}
    assert set(e.hass.services.handlers) == {("light", "turn_on")}
    assert e.removed_filters == e.installed_filters


@pytest.mark.asyncio
async def test_failed_platform_unload_keeps_owner_and_services(setup_environment):
    e = setup_environment
    await e.module.async_setup_entry(e.hass, e.first)
    handlers = dict(e.hass.services.handlers)
    e.hass.config_entries.unload_result = False
    assert await e.module.async_unload_entry(e.hass, e.first) is False
    assert e.hass.data[DOMAIN]["entry_id"] == "first"
    assert e.hass.services.handlers == handlers
    assert e.created[0].close_count == e.created[0].quality.close_count == 0
    assert e.removed_filters == []
