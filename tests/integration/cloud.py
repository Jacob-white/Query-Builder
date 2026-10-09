"""
Cloud / managed engines that cannot run from a container. Each runs ONLY when
its environment variables are set and is skipped (with the exact variable names
to set) otherwise. See docs/TESTING_LIVE.md, "Cloud engines".

The environment variable names are ``QB_IT_<ENGINE>_<KEY>``; authentication that
the vendor SDK already resolves from its own environment (AWS credentials,
``GOOGLE_APPLICATION_CREDENTIALS``) is not duplicated here.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CloudEngine:
    name: str
    connector: str  # registry name
    required: tuple[str, ...]  # env keys (suffix after QB_IT_<NAME>_)
    kwargs: Callable[[dict[str, str]], dict[str, Any]]
    drivers: tuple[str, ...]
    pip: str
    secret_kw: str | None = None  # connector kwarg holding a password / token
    note: str = ""

    def env_name(self, key: str) -> str:
        return f"QB_IT_{self.name.upper()}_{key}"

    def missing(self) -> list[str]:
        return [
            self.env_name(k)
            for k in self.required
            if not os.environ.get(self.env_name(k))
        ]

    def values(self) -> dict[str, str]:
        return {
            k: os.environ[self.env_name(k)]
            for k in self.required
            if os.environ.get(self.env_name(k))
        }

    def optional(self, key: str, default: str = "") -> str:
        return os.environ.get(self.env_name(key), default)

    def connector_class_keys(self) -> list[str]:
        from query_builder.connectors.registry import ConnectorRegistry

        cls = ConnectorRegistry._registry[self.connector]
        return [f"{cls.__module__}.{cls.__qualname__}"]


def _snowflake(v: dict[str, str]) -> dict[str, Any]:
    return {
        "account": v["ACCOUNT"],
        "user": v["USER"],
        "password": v["PASSWORD"],
        "warehouse": v["WAREHOUSE"],
        "database": v["DATABASE"],
        "schema_name": os.environ.get("QB_IT_SNOWFLAKE_SCHEMA", "PUBLIC"),
    }


def _bigquery(v: dict[str, str]) -> dict[str, Any]:
    return {"dataset": v["DATASET"]}


def _databricks(v: dict[str, str]) -> dict[str, Any]:
    return {
        "server_hostname": v["HOST"],
        "http_path": v["HTTP_PATH"],
        "access_token": v["TOKEN"],
        "catalog": os.environ.get("QB_IT_DATABRICKS_CATALOG", "main"),
        "schema_name": os.environ.get("QB_IT_DATABRICKS_SCHEMA", "default"),
    }


def _redshift(v: dict[str, str]) -> dict[str, Any]:
    return {
        "host": v["HOST"],
        "port": int(os.environ.get("QB_IT_REDSHIFT_PORT", "5439")),
        "user": v["USER"],
        "password": v["PASSWORD"],
        "database": v["DATABASE"],
    }


def _athena(v: dict[str, str]) -> dict[str, Any]:
    return {
        "s3_staging_dir": v["S3_STAGING_DIR"],
        "region_name": v["REGION"],
        "schema_name": os.environ.get("QB_IT_ATHENA_DATABASE", "default"),
    }


def _synapse(v: dict[str, str]) -> dict[str, Any]:
    return {
        "server": v["SERVER"],
        "user": v["USER"],
        "password": v["PASSWORD"],
        "database": v["DATABASE"],
        "port": os.environ.get("QB_IT_SYNAPSE_PORT", "1433"),
    }


CLOUD: dict[str, CloudEngine] = {
    c.name: c
    for c in (
        CloudEngine(
            "snowflake",
            "snowflake",
            ("ACCOUNT", "USER", "PASSWORD", "WAREHOUSE", "DATABASE"),
            _snowflake,
            ("snowflake.connector",),
            "snowflake-connector-python",
            secret_kw="password",
        ),
        CloudEngine(
            "bigquery",
            "bigquery",
            ("DATASET",),
            _bigquery,
            ("google.cloud.bigquery",),
            "google-cloud-bigquery",
            note="also set GOOGLE_APPLICATION_CREDENTIALS (service-account JSON)",
        ),
        CloudEngine(
            "databricks",
            "databricks",
            ("HOST", "HTTP_PATH", "TOKEN"),
            _databricks,
            ("databricks.sql",),
            "databricks-sql-connector",
            secret_kw="access_token",
        ),
        CloudEngine(
            "redshift",
            "redshift",
            ("HOST", "USER", "PASSWORD", "DATABASE"),
            _redshift,
            ("redshift_connector",),
            "redshift-connector",
            secret_kw="password",
        ),
        CloudEngine(
            "athena",
            "athena",
            ("S3_STAGING_DIR", "REGION"),
            _athena,
            ("pyathena",),
            "pyathena",
            note="AWS credentials come from the standard AWS environment/profile",
        ),
        CloudEngine(
            "synapse",
            "mssql",
            ("SERVER", "USER", "PASSWORD", "DATABASE"),
            _synapse,
            ("pymssql", "pyodbc"),
            "pymssql",
            secret_kw="password",
            note="Azure Synapse dedicated/serverless SQL pool via the SQL Server connector",
        ),
    )
}
