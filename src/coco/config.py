"""Configuration loader for CoCo agent.

Reads YAML configuration with environment variable interpolation.
Provides a single cached config singleton via get_config().
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DeploymentConfig:
    """Deployment settings."""

    mode: str  # demo | dev | staging | prod


@dataclass
class WorkspaceConfig:
    """Databricks workspace connection."""

    host: str
    client_id: str
    client_secret: str


@dataclass
class CatalogConfig:
    """UC catalog and volumes."""

    name: str
    schema: str
    volumes: Dict[str, str]


@dataclass
class TablesConfig:
    """Table names."""

    patients: str
    diagnoses: str
    prescriptions: str
    procedures: str
    claims: str
    suppliers: str
    agent_inference_table: str


@dataclass
class LLMConfig:
    """LLM endpoint configuration."""

    endpoint: str
    gateway_route: str
    temperature: float
    max_tokens: int


@dataclass
class SQLWarehouseConfig:
    """SQL warehouse settings."""

    id: str
    wait_timeout: str
    on_wait_timeout: str
    result_disposition: str
    result_format: str


@dataclass
class LakebaseConfig:
    """Session store configuration."""

    instance: str
    database: str
    schema: str
    pool: Dict[str, Any]


@dataclass
class VectorSearchConfig:
    """Vector search index configuration."""

    endpoint_name: str
    index_name: str
    embedding_model: str
    source_table: str
    primary_key: str
    text_column: str
    hybrid: bool


@dataclass
class AgentEndpointConfig:
    """Model Serving endpoint configuration."""

    name: str
    scale_to_zero: bool
    min_provisioned_concurrency: int
    max_provisioned_concurrency: int
    workload_size: str


@dataclass
class PromptRegistryConfig:
    """MLflow Prompt Registry names."""

    cohort_query: str
    sql_generator: str
    clinical_codes: str
    response_synthesizer: str


@dataclass
class MLFlowConfig:
    """MLflow settings."""

    experiment_name: str
    prompt_registry: PromptRegistryConfig


@dataclass
class AppConfig:
    """Application settings."""

    title: str
    max_message_tokens: int
    sse_heartbeat_seconds: int
    polling_fallback_after_seconds: int
    agent_endpoint_url: str


@dataclass
class GuardrailsConfig:
    """SQL execution guardrails."""

    sql_read_only: bool
    allowed_schemas: list[str]
    max_result_rows: int


@dataclass
class EvaluationConfig:
    """Evaluation settings."""

    scenarios_file: str
    scorers: list[str]


@dataclass
class DataGeneratorConfig:
    """Synthetic data generation settings."""

    num_patients: int
    num_suppliers: int
    start_date: str
    end_date: str
    seed: int


@dataclass
class CocoConfig:
    """Root configuration object."""

    deployment: DeploymentConfig
    workspace: WorkspaceConfig
    catalog: CatalogConfig
    tables: TablesConfig
    llm: LLMConfig
    sql_warehouse: SQLWarehouseConfig
    lakebase: LakebaseConfig
    vector_search: VectorSearchConfig
    agent_endpoint: AgentEndpointConfig
    mlflow: MLFlowConfig
    app: AppConfig
    guardrails: GuardrailsConfig
    evaluation: EvaluationConfig
    data_generator: DataGeneratorConfig


_cached_config: Optional[CocoConfig] = None


def _interpolate_env_vars(data: Any) -> Any:
    """Recursively replace ${VAR} patterns with environment variables."""
    if isinstance(data, dict):
        return {k: _interpolate_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_interpolate_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Replace ${VAR} with os.environ.get(VAR, "") and ${VAR:default}
        # with os.environ.get(VAR, default). The `:default` form lets a
        # config key declare its fallback inline (e.g.
        # `"${COCO_MLFLOW_EXPERIMENT:/Shared/coco-agent}"`) which keeps
        # per-user / per-workspace overrides tidy.
        def replacer(match: Any) -> str:
            token = match.group(1)
            if ":" in token:
                var_name, default = token.split(":", 1)
            else:
                var_name, default = token, ""
            return os.environ.get(var_name, default)

        return re.sub(r"\$\{([^}]+)\}", replacer, data)
    else:
        return data


def get_config() -> CocoConfig:
    """Load and cache configuration from YAML file.

    Reads path from COCO_CONFIG_PATH env var or defaults to
    config/default.yaml relative to repo root.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    config_path = os.environ.get("COCO_CONFIG_PATH", "config/default.yaml")
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at {config_path.absolute()}")

    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    # Interpolate environment variables
    raw_config = _interpolate_env_vars(raw_config)

    # Build nested dataclass structure
    _cached_config = CocoConfig(
        deployment=DeploymentConfig(**raw_config["deployment"]),
        workspace=WorkspaceConfig(**raw_config["workspace"]),
        catalog=CatalogConfig(**raw_config["catalog"]),
        tables=TablesConfig(**raw_config["tables"]),
        llm=LLMConfig(**raw_config["llm"]),
        sql_warehouse=SQLWarehouseConfig(**raw_config["sql_warehouse"]),
        lakebase=LakebaseConfig(**raw_config["lakebase"]),
        vector_search=VectorSearchConfig(**raw_config["vector_search"]),
        agent_endpoint=AgentEndpointConfig(**raw_config["agent_endpoint"]),
        mlflow=MLFlowConfig(
            experiment_name=raw_config["mlflow"]["experiment_name"],
            prompt_registry=PromptRegistryConfig(**raw_config["mlflow"]["prompt_registry"]),
        ),
        app=AppConfig(**raw_config["app"]),
        guardrails=GuardrailsConfig(**raw_config["guardrails"]),
        evaluation=EvaluationConfig(**raw_config["evaluation"]),
        data_generator=DataGeneratorConfig(**raw_config["data_generator"]),
    )

    # Validate that critical fields resolved to non-empty values.
    # Each tuple is (dotted field path, actual value, env var hint).
    _required = [
        ("sql_warehouse.id", _cached_config.sql_warehouse.id, "COCO_WAREHOUSE_ID"),
        ("catalog.name", _cached_config.catalog.name, "COCO_CATALOG_NAME"),
        ("catalog.schema", _cached_config.catalog.schema, "COCO_CATALOG_SCHEMA"),
        ("llm.endpoint", _cached_config.llm.endpoint, "COCO_LLM_ENDPOINT"),
    ]
    missing = [(field, env) for field, val, env in _required if not val or not val.strip()]
    if missing:
        for field, env in missing:
            logger.warning(
                "Config field '%s' is empty. Set the %s environment variable or update %s. "
                "Features that depend on this field will fail at runtime.",
                field,
                env,
                config_path,
            )
        names = ", ".join(f for f, _ in missing)
        logger.warning("Missing config values (non-fatal): %s", names)

    return _cached_config
