from typing import List
from dataclasses import dataclass
from interfaces_v2 import IPlugin


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    type: str
    entrypoint: str
    interfaces_implemented: List[str]
    config_schema: dict


class ExampleNewsPlugin(IPlugin):
    def __init__(self):
        self._config = {}

    @property
    def manifest(self) -> dict:
        return PluginManifest(
            id="example_news_plugin",
            name="Example News Source",
            version="1.0.0",
            type="data_source",
            entrypoint="plugin.py:ExampleNewsPlugin",
            interfaces_implemented=["INewsProvider"],
            config_schema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string"},
                    "base_url": {"type": "string"},
                },
            },
        )

    def on_load(self, config: dict) -> None:
        self._config = config
        self._api_key = config.get("api_key", "mock-key")
        self._base_url = config.get("base_url", "https://example.com/api")

    def on_unload(self) -> None:
        self._api_key = None
        self._base_url = None
        self._config = {}

    def search(self, query: str, max_results: int = 5) -> str:
        return (
            f"[ExampleNewsPlugin] query='{query}' max_results={max_results} "
            f"api_key='{self._api_key[:4]}...' base_url='{self._base_url}'\n"
            f"  - Mock article 1: '{query} market rally'\n"
            f"  - Mock article 2: '{query} earnings report'\n"
            f"  - Mock article 3: '{query} analyst upgrade'"
        )
