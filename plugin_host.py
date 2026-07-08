from __future__ import annotations
import json
import logging
import importlib
import importlib.util
import inspect
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from interfaces_v2 import IPlugin

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    type: str  # data_source / strategy / notifier / agent
    entrypoint: str  # e.g. "plugin.py:Plugin"
    interfaces_implemented: list[str]
    config_schema: dict


class PluginHost:
    def __init__(self, plugin_dir: str | Path = "plugins"):
        self._plugin_dir = Path(plugin_dir)
        self._manifests: dict[str, PluginManifest] = {}
        self._loaded: dict[str, IPlugin] = {}

    def discover(self) -> None:
        self._manifests.clear()
        for manifest_path in sorted(self._plugin_dir.glob("*/plugin.json")):
            try:
                with open(manifest_path) as f:
                    data = json.load(f)
                manifest = PluginManifest(**data)
                if not all([manifest.id, manifest.name, manifest.version, manifest.type, manifest.entrypoint]):
                    logger.warning("Skipping %s: missing required fields", manifest_path)
                    continue
                self._manifests[manifest.id] = manifest
                logger.info("Discovered plugin '%s' (%s)", manifest.id, manifest.name)
            except Exception as e:
                logger.error("Failed to parse manifest %s: %s", manifest_path, e)

    def load(self, plugin_id: str) -> IPlugin | None:
        manifest = self._manifests.get(plugin_id)
        if manifest is None:
            logger.error("Plugin '%s' not found among discovered manifests", plugin_id)
            return None

        try:
            module_rel, class_name = manifest.entrypoint.split(":", 1)
            module_path = self._plugin_dir / manifest.id / module_rel

            spec = importlib.util.spec_from_file_location(f"plugin_{manifest.id}", module_path)
            if spec is None or spec.loader is None:
                logger.error("Failed to create module spec for '%s'", plugin_id)
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            cls = getattr(module, class_name, None)
            if cls is None:
                logger.error("Class '%s' not found in module '%s'", class_name, module_path)
                return None

            instance = cls()

            for iface_name in manifest.interfaces_implemented:
                iface_cls = self._find_interface_class(iface_name)
                if iface_cls is None:
                    logger.warning(
                        "Interface '%s' not found in interfaces_v2; skipping validation", iface_name
                    )
                    continue
                if not isinstance(instance, iface_cls):
                    logger.error(
                        "Plugin '%s' does not implement required interface '%s'",
                        plugin_id, iface_name,
                    )
                    return None

            instance.on_load({})
            self._loaded[plugin_id] = instance
            logger.info("Loaded plugin '%s'", plugin_id)
            return instance

        except Exception as e:
            logger.exception("Failed to load plugin '%s': %s", plugin_id, e)
            return None

    def unload(self, plugin_id: str) -> None:
        instance = self._loaded.pop(plugin_id, None)
        if instance is None:
            logger.warning("Plugin '%s' is not loaded, nothing to unload", plugin_id)
            return
        try:
            instance.on_unload()
            logger.info("Unloaded plugin '%s'", plugin_id)
        except Exception as e:
            logger.exception("Error during unload of plugin '%s': %s", plugin_id, e)

    def load_all(self) -> None:
        self.discover()
        for pid in list(self._manifests):
            self.load(pid)

    def get(self, plugin_id: str) -> IPlugin | None:
        return self._loaded.get(plugin_id)

    def list_plugins(self) -> list[PluginManifest]:
        return list(self._manifests.values())

    def invoke(self, plugin_id: str, action: str, payload: dict) -> Any:
        instance = self._loaded.get(plugin_id)
        if instance is None:
            logger.error("Plugin '%s' is not loaded", plugin_id)
            return None
        method = getattr(instance, action, None)
        if method is None:
            logger.error("Action '%s' not found on plugin '%s'", action, plugin_id)
            return None
        try:
            return method(**payload)
        except Exception as e:
            logger.exception("Invocation of '%s' on plugin '%s' failed: %s", action, plugin_id, e)
            return None

    @staticmethod
    def _find_interface_class(name: str) -> type | None:
        import interfaces_v2
        return getattr(interfaces_v2, name, None)
