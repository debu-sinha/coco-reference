"""Tests for configuration loading and validation."""
import os
import tempfile
from pathlib import Path

import pytest

from coco.config import (
    CocoConfig,
    get_config,
    _interpolate_env_vars,
)


class TestConfigInterpolation:
    """Test environment variable interpolation."""

    def test_simple_env_var(self) -> None:
        """Test single environment variable replacement."""
        os.environ["TEST_VAR"] = "test_value"
        result = _interpolate_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_test_value_suffix"
        del os.environ["TEST_VAR"]

    def test_missing_env_var(self) -> None:
        """Test missing env var returns empty string."""
        result = _interpolate_env_vars("value_${NONEXISTENT_VAR}_end")
        assert result == "value__end"

    def test_nested_dict_interpolation(self) -> None:
        """Test recursive interpolation in nested dicts."""
        os.environ["DB_HOST"] = "localhost"
        data = {
            "host": "${DB_HOST}",
            "nested": {
                "url": "http://${DB_HOST}:5432"
            }
        }
        result = _interpolate_env_vars(data)
        assert result["host"] == "localhost"
        assert result["nested"]["url"] == "http://localhost:5432"
        del os.environ["DB_HOST"]

    def test_list_interpolation(self) -> None:
        """Test interpolation in lists."""
        os.environ["SCHEMA_1"] = "schema_a"
        data = ["${SCHEMA_1}", "schema_b", "schema_c"]
        result = _interpolate_env_vars(data)
        assert result[0] == "schema_a"
        assert result[1] == "schema_b"
        del os.environ["SCHEMA_1"]

    def test_no_interpolation_needed(self) -> None:
        """Test data without env vars passes through."""
        data = {
            "int_value": 42,
            "bool_value": True,
            "string_value": "no_variables_here",
        }
        result = _interpolate_env_vars(data)
        assert result == data


class TestConfigLoading:
    """Test configuration file loading."""

    def test_load_default_config(self, mock_config: CocoConfig) -> None:
        """Test that default config loads with expected structure."""
        assert mock_config.deployment.mode == "test"
        assert mock_config.catalog.name == "coco_test"
        assert mock_config.tables.patients == "patients"
        assert len(mock_config.allowed_schemas) == 1

    def test_config_missing_file(self) -> None:
        """Test error on missing config file."""
        os.environ["COCO_CONFIG_PATH"] = "/nonexistent/path/config.yaml"
        # Reset cached config to force reload
        import coco.config
        coco.config._cached_config = None

        with pytest.raises(FileNotFoundError):
            coco.config.get_config()

        del os.environ["COCO_CONFIG_PATH"]
        coco.config._cached_config = None

    def test_config_caching(self) -> None:
        """Test that get_config caches the result."""
        import coco.config
        coco.config._cached_config = None

        # First call
        config1 = coco.config.get_config()
        # Second call should return same object
        config2 = coco.config.get_config()

        assert config1 is config2


class TestCocoConfigDataclasses:
    """Test configuration dataclass validation."""

    def test_workspace_config(self) -> None:
        """Test workspace config dataclass."""
        from coco.config import WorkspaceConfig

        cfg = WorkspaceConfig(
            host="https://example.com",
            client_id="test-id",
            client_secret="test-secret",
        )
        assert cfg.host == "https://example.com"
        assert cfg.client_id == "test-id"

    def test_catalog_config_with_volumes(self) -> None:
        """Test catalog config with nested volumes dict."""
        from coco.config import CatalogConfig

        cfg = CatalogConfig(
            name="test_cat",
            schema="test_schema",
            volumes={"knowledge": "vol1", "artifacts": "vol2"},
        )
        assert cfg.volumes["knowledge"] == "vol1"

    def test_llm_config_temperature_bounds(self) -> None:
        """Test LLM config can be created with valid temperature."""
        from coco.config import LLMConfig

        cfg = LLMConfig(
            endpoint="test-endpoint",
            gateway_route="test-route",
            temperature=0.5,
            max_tokens=2048,
        )
        assert cfg.temperature == 0.5

    def test_evaluation_config_scorers(self) -> None:
        """Test evaluation config with scorer list."""
        from coco.config import EvaluationConfig

        cfg = EvaluationConfig(
            scenarios_file="scenarios.yaml",
            scorers=["sql_validity", "response_relevance"],
        )
        assert len(cfg.scorers) == 2
        assert "sql_validity" in cfg.scorers
