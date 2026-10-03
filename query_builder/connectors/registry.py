"""
Pluggable Connector Registry.
=============================
Provides discovery, registration, and instantiation for query builder database connectors.
"""

from __future__ import annotations

from typing import Any, ClassVar, TypeVar

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector, ConnectorError
from query_builder.dialects import BaseDialect

T = TypeVar("T", bound=BaseConnector | AsyncBaseConnector)


class ConnectorRegistry:
    """Registry maintaining available database connector implementations."""

    _registry: ClassVar[dict[str, type[BaseConnector | AsyncBaseConnector]]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        connector_cls: type[BaseConnector | AsyncBaseConnector],
        aliases: list[str] | None = None,
        dialect: str | BaseDialect | None = None,
    ) -> None:
        """Registers a connector class under a primary name and optional aliases."""
        if not (
            isinstance(connector_cls, type)
            and issubclass(connector_cls, (BaseConnector, AsyncBaseConnector))
        ):
            name_repr = (
                connector_cls.__name__
                if isinstance(connector_cls, type)
                else type(connector_cls).__name__
            )
            raise TypeError(
                f"Connector class must inherit from BaseConnector, got {name_repr}"
            )
        if not isinstance(name, str):
            raise TypeError(
                f"Connector name must be a string, got {type(name).__name__}"
            )
        clean_name = name.lower().strip()
        if not clean_name:
            raise ValueError("Connector name cannot be empty.")

        if dialect is not None:
            if isinstance(dialect, str):
                connector_cls.dialect_name = dialect
            elif isinstance(dialect, BaseDialect):
                from query_builder.dialects import register_dialect

                register_dialect(dialect.name, dialect)
                connector_cls.dialect_name = dialect.name
            else:
                raise TypeError(
                    f"Dialect must be a string or BaseDialect instance, got {type(dialect).__name__}"
                )

        cls._registry[clean_name] = connector_cls
        if aliases:
            for alias in aliases:
                clean_alias = alias.lower().strip()
                if clean_alias:
                    cls._registry[clean_alias] = connector_cls

    @classmethod
    def unregister(cls, name: str) -> None:
        """Removes a connector from the registry."""
        clean_name = name.lower().strip()
        cls._registry.pop(clean_name, None)

    @classmethod
    def get(cls, name: str, **kwargs: Any) -> Any:
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
    name: str | type[T],
    connector_cls: type[T] | None = None,
    aliases: list[str] | None = None,
    dialect: str | BaseDialect | None = None,
) -> Any:
    """
    Registers a connector into ConnectorRegistry.

    Supports:
    - Bare decorator: @register_connector
    - Decorator with name: @register_connector("sqlite", aliases=[...], dialect=...)
    - Standard function: register_connector("sqlite", SQLiteConnector, aliases=[...], dialect=...)
    """
    if isinstance(name, type):
        # Bare decorator: @register_connector
        raw_name = name.__name__.lower()
        inferred = (
            raw_name[:-9]
            if raw_name.endswith("connector") and len(raw_name) > 9
            else raw_name
        )
        ConnectorRegistry.register(inferred, name, aliases=aliases, dialect=dialect)
        return name

    if not isinstance(name, str):
        raise TypeError(
            f"Connector name must be a string or connector class, got {type(name).__name__}"
        )

    if connector_cls is None:
        # Decorator factory: @register_connector("name", aliases=..., dialect=...)
        def decorator(cls_target: type[T]) -> type[T]:
            ConnectorRegistry.register(
                name, cls_target, aliases=aliases, dialect=dialect
            )
            return cls_target

        return decorator

    # Standard function call: register_connector("name", cls, aliases=..., dialect=...)
    ConnectorRegistry.register(name, connector_cls, aliases=aliases, dialect=dialect)
    return connector_cls


def get_connector(name: str, **kwargs: Any) -> Any:
    """Helper to retrieve an instantiated connector."""
    return ConnectorRegistry.get(name, **kwargs)


def list_connectors() -> list[str]:
    """Helper to list registered connector names."""
    return ConnectorRegistry.list_available()
