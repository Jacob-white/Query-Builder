"""
Pluggable Connector Registry.
=============================
Provides discovery, registration, and instantiation for query builder database connectors.
"""

from __future__ import annotations

from typing import Any, ClassVar

from query_builder.connectors.base import BaseConnector, ConnectorError


class ConnectorRegistry:
    """Registry maintaining available database connector implementations."""

    _registry: ClassVar[dict[str, type[BaseConnector]]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        connector_cls: type[BaseConnector],
        aliases: list[str] | None = None,
    ) -> None:
        """Registers a connector class under a primary name and optional aliases."""
        if not issubclass(connector_cls, BaseConnector):
            raise TypeError(
                f"Connector class must inherit from BaseConnector, got {connector_cls.__name__}"
            )
        clean_name = name.lower().strip()
        cls._registry[clean_name] = connector_cls
        if aliases:
            for alias in aliases:
                cls._registry[alias.lower().strip()] = connector_cls

    @classmethod
    def unregister(cls, name: str) -> None:
        """Removes a connector from the registry."""
        clean_name = name.lower().strip()
        cls._registry.pop(clean_name, None)

    @classmethod
    def get(cls, name: str, **kwargs: Any) -> BaseConnector:
        """Instantiates and returns the connector registered for the specified name."""
        clean_name = name.lower().strip()
        if clean_name not in cls._registry:
            available = ", ".join(sorted(cls._registry.keys()))
            raise ConnectorError(
                f"No connector registered for '{name}'. Available connectors: [{available}]"
            )
        return cls._registry[clean_name](**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        """Returns a sorted list of registered connector names."""
        return sorted(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        """Clears all registered connectors."""
        cls._registry.clear()


def register_connector(
    name: str, connector_cls: type[BaseConnector], aliases: list[str] | None = None
) -> None:
    """Helper to register a connector."""
    ConnectorRegistry.register(name, connector_cls, aliases)


def get_connector(name: str, **kwargs: Any) -> BaseConnector:
    """Helper to retrieve an instantiated connector."""
    return ConnectorRegistry.get(name, **kwargs)


def list_connectors() -> list[str]:
    """Helper to list registered connector names."""
    return ConnectorRegistry.list_available()
