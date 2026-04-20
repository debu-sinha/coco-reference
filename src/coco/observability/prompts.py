"""MLflow Prompt Registry integration for CoCo.

Manages prompt registration, versioning, and loading with fallback
to bundled defaults if registry is unreachable.
"""
from __future__ import annotations

import logging
from typing import Optional

import mlflow

from coco.config import get_config
from coco.observability.prompts_default import DEFAULT_PROMPTS

logger = logging.getLogger(__name__)


def register_prompt(
    name: str,
    template: str,
    version_alias: str = "production",
) -> str:
    """Register or update a prompt in MLflow Prompt Registry.

    Idempotent: updates existing prompt if already registered.

    Args:
        name: Prompt name (e.g., "coco.sql_generator")
        template: Prompt template string (may include {placeholders})
        version_alias: Alias for this version (default "production")

    Returns:
        Registered prompt name

    Raises:
        RuntimeError: If registration fails and not in fallback mode
    """
    try:
        # Register via MLflow Prompt Registry
        prompt = mlflow.genai.register_prompt(
            name=name,
            prompt_template=template,
            description=f"Prompt: {name}",
            version_alias=version_alias,
        )

        logger.info(
            "Registered prompt %s; version_alias=%s",
            name,
            version_alias,
        )

        return prompt

    except Exception as e:
        logger.warning(
            "Failed to register prompt %s: %s; using fallback",
            name,
            e,
        )

        # Fallback: return name for load_prompt to handle
        return name


def load_prompt(
    name: str,
    version_alias: str = "production",
) -> str:
    """Load prompt from MLflow Prompt Registry.

    Falls back to bundled defaults if registry is unreachable.

    Args:
        name: Prompt name (e.g., "coco.sql_generator")
        version_alias: Version to load (default "production")

    Returns:
        Prompt template string

    Raises:
        ValueError: If prompt not found in registry or defaults
    """
    # Try MLflow Prompt Registry first
    try:
        prompt = mlflow.genai.load_prompt(
            name=name,
            version_alias=version_alias,
        )

        if prompt:
            logger.debug("Loaded prompt %s from registry", name)
            return prompt

    except Exception as e:
        logger.debug(
            "Failed to load from registry %s: %s; trying defaults",
            name,
            e,
        )

    # Fallback to bundled defaults
    if name in DEFAULT_PROMPTS:
        logger.info("Using default prompt for %s", name)
        return DEFAULT_PROMPTS[name]

    raise ValueError(
        f"Prompt '{name}' not found in registry or defaults"
    )


def get_prompt_template(
    name: str,
    variables: dict | None = None,
) -> str:
    """Load prompt and optionally fill in variables.

    Convenience wrapper around load_prompt with format support.

    Args:
        name: Prompt name
        variables: Dict of variables to format into template

    Returns:
        Formatted prompt string (or original if no variables)

    Example:
        prompt = get_prompt_template(
            "coco.sql_generator",
            variables={"table_name": "patients", "columns": "..."}
        )
    """
    template = load_prompt(name)

    if variables:
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(
                "Missing variable in prompt %s: %s",
                name,
                e,
            )
            return template

    return template
