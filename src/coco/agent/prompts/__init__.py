"""Prompt registry integration and default prompts.

Loads DSPy signature instructions from MLflow Prompt Registry with
fallback to bundled defaults. The prompts live in MLflow so they can
be versioned, A/B tested, and updated without redeploying the agent.

The setup notebook registers the defaults on first run. The DSPy
optimizer (03_optimize_dspy.py) writes optimized prompts back.
"""

from __future__ import annotations

import logging

from coco.config import get_config

logger = logging.getLogger(__name__)


DEFAULTS: dict[str, str] = {
    "cohort_query": (
        "You are a clinical data analyst for a healthcare real-world data "
        "platform. Answer questions about patient cohorts by querying the "
        "database on Databricks.\n\n"
        "You have tools for inspecting the database schema, looking up "
        "clinical codes (ICD-10, NDC, CPT), generating SQL, executing SQL, "
        "and searching a clinical knowledge base.\n\n"
        "ALWAYS call inspect_schema first so you know the real table names "
        "and column types before generating SQL. ALWAYS use fully-qualified "
        "table names. ALWAYS pass generated SQL through execute_sql to get "
        "real results before answering."
    ),
    "clinical_codes": (
        "Identify clinical codes from natural language.\n\n"
        "Converts user input describing a medical condition, medication, or "
        "procedure into standardized codes (ICD-10, NDC, CPT) with confidence."
    ),
    "sql_generator": (
        "Generate SQL for cohort queries.\n\n"
        "Takes natural language cohort criteria and schema context, "
        "produces executable SQL and validation rationale."
    ),
    "response_synthesizer": (
        "Synthesize final response to user.\n\n"
        "Takes user query, tool results, and execution context, "
        "produces natural language response with sample data and SQL."
    ),
}


def load_prompt(prompt_name: str) -> str:
    """Load a prompt from MLflow Prompt Registry, falling back to DEFAULTS.

    The registry name is the 3-part UC-qualified name
    ``<catalog>.<schema>.<local_name>`` — MLflow 3 managed prompts live
    inside UC and reject single-part names like ``coco.cohort_query``
    with INVALID_PARAMETER_VALUE. Earlier code used the short form and
    every call silently fell back to DEFAULTS, which masked the fact
    that nothing was ever being served from the registry.
    """
    registry_name = _registry_name(prompt_name)
    if registry_name:
        try:
            import mlflow.genai

            prompt_obj = mlflow.genai.load_prompt(f"prompts:/{registry_name}/production")
            template = getattr(prompt_obj, "template", None) or str(prompt_obj)
            if template.strip():
                logger.debug("Loaded prompt '%s' from registry '%s'", prompt_name, registry_name)
                return template.strip()
        except Exception as e:
            logger.info("Registry prompt '%s' unavailable (%s), using default", registry_name, e)

    return DEFAULTS.get(prompt_name, DEFAULTS["cohort_query"])


def register_defaults() -> dict[str, str]:
    """Register all default prompts to MLflow Prompt Registry.

    Returns a dict of {prompt_name: registry_name} for prompts that
    were registered. Skips prompts that already exist.

    Raises RuntimeError if the Managed MLflow Prompt Registry preview
    flag is disabled on the workspace (FEATURE_DISABLED on
    CreatePrompt). This used to be a silent warning. In earlier test deployments we saw a
    setup run complete "successfully" with ZERO prompts registered,
    which then masqueraded as a working deployment until the agent's
    first turn fell back to DEFAULTS and the optimize notebook errored
    out. Hard-failing here forces the deployer to flip the
    preview flag before moving on, which is what the preflight check
    also reports.
    """
    import mlflow.genai

    registered: dict[str, str] = {}
    errors: list[str] = []
    for prompt_name, template in DEFAULTS.items():
        registry_name = _registry_name(prompt_name)
        if not registry_name:
            logger.warning(
                "No catalog/schema available for prompt '%s'; skipping registration "
                "(set COCO_CATALOG_NAME and COCO_SCHEMA_NAME).",
                prompt_name,
            )
            continue
        try:
            prompt_obj = mlflow.genai.register_prompt(name=registry_name, template=template)
            version = int(getattr(prompt_obj, "version", 1) or 1)
            registered[prompt_name] = registry_name
            logger.info("Registered prompt: %s -> %s v%d", prompt_name, registry_name, version)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            lower = msg.lower()
            if "already exists" in lower or "RESOURCE_ALREADY_EXISTS" in msg:
                logger.info("Prompt '%s' already registered, skipping", registry_name)
                registered[prompt_name] = registry_name
                version = 1  # assume v1 for aliasing; harmless if there are already newer versions
            elif "FEATURE_DISABLED" in msg or "prompt registry is not enabled" in lower:
                errors.append(
                    f"{registry_name}: Prompt Registry preview flag is OFF "
                    f"(FEATURE_DISABLED on CreatePrompt)"
                )
                continue
            else:
                errors.append(f"{registry_name}: {type(e).__name__}: {msg[:200]}")
                continue

        # Always set @production alias on the registered version so the
        # agent's load_prompt("prompts:/name/production") works from the
        # very first deploy. Without this, a fresh setup run registers
        # prompts but leaves no alias, so load_prompt @production raises
        # and the agent falls back to DEFAULTS silently.
        try:
            mlflow.genai.set_prompt_alias(name=registry_name, version=version, alias="production")
            logger.info("Set @production alias on %s v%d", registry_name, version)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not set @production alias on %s: %s", registry_name, e)

    if errors:
        joined = "\n  - ".join(errors)
        raise RuntimeError(
            "register_defaults() failed for one or more prompts. Setup cannot "
            "proceed with a working optimizer or Prompt Registry integration.\n"
            f"  - {joined}\n\n"
            "Fix: enable the 'Managed MLflow Prompt Registry' preview feature "
            "under workspace Settings > Preview features, then re-run setup. "
            "Run scripts/preflight_check.py to verify before re-running."
        )
    return registered


def _registry_name(prompt_name: str) -> str | None:
    """Build the 3-part UC-qualified prompt name from config.

    Returns ``<catalog>.<schema>.<local_name>`` when both catalog and
    schema are resolvable from the loaded config, otherwise None. The
    local_name comes from config.mlflow.prompt_registry.<prompt_name>
    when present (so per-prompt overrides are still possible), and from
    the prompt_name argument itself as a fallback.
    """
    try:
        config = get_config()
    except Exception:
        return None

    catalog = getattr(config.catalog, "name", "") or ""
    schema = getattr(config.catalog, "schema", "") or ""
    if not catalog or not schema:
        return None

    # Allow the YAML to override the local leaf name per prompt.
    # Defaults to the prompt_name argument if the override is missing
    # or is a legacy "coco.<name>"-style dotted value (we strip any
    # dots since MLflow rejects dotted leaf names).
    override = getattr(config.mlflow.prompt_registry, prompt_name, "") or ""
    leaf = override.rsplit(".", 1)[-1] if override else prompt_name
    leaf = leaf.replace(".", "_")

    return f"{catalog}.{schema}.{leaf}"
