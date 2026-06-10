"""Domain configuration loader for CoCo.

CoCo is a domain-agnostic agentic-AI reference. The healthcare cohort
analysis is just one domain spec. To fork CoCo for a different domain
(retail listings, legal codes, manufacturing parts), drop a new
`domains/<your-domain>/domain.yaml` in the repo and point the bundle
at it via `--var domain=<your-domain>`. Everything below this module
reads the loaded Domain object instead of hardcoded names.

See `docs/FORK_GUIDE.md` for the fork-and-go walkthrough.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DomainTable:
    """One UC table the agent is allowed to query."""

    name: str
    description: str = ""
    primary_key: str = ""
    foreign_keys: dict[str, str] = field(default_factory=dict)


@dataclass
class DomainOntology:
    """Ontology tool config.

    Wires the agent's domain-entity-lookup tool (e.g. identify_clinical_codes
    for healthcare, identify_product_attributes for marketplace) to the
    right Vector Search index.
    """

    tool_name: str
    tool_description: str
    index_name: str
    text_column: str = "content"
    primary_key: str = "chunk_id"
    top_k: int = 5


@dataclass
class DomainKnowledge:
    """RAG corpus config."""

    source_volume_path: str
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 50


@dataclass
class DomainSqlGuardrails:
    """SQL safety filters for execute_sql."""

    allowed_schemas: list[str] = field(default_factory=list)
    blocked_keywords: list[str] = field(default_factory=list)


@dataclass
class Domain:
    """The active domain CoCo is running as.

    Loaded once at process start via `load_domain()` and read by the
    agent code, prompts, tools, and setup notebook.
    """

    name: str
    display_name: str
    description: str
    user_role: str
    entity_type: str
    primary_action: str
    data_mode: str
    synthetic_generator: str
    tables: list[DomainTable]
    ontology: DomainOntology
    knowledge: DomainKnowledge
    sql_guardrails: DomainSqlGuardrails
    evaluation_golden_set_path: str
    spec_path: str  # where the domain.yaml that produced this object lives

    @property
    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    def render_template(self, text: str) -> str:
        """Substitute domain placeholders in a template string.

        Used by the prompt system so prompts like
        "You help a {user_role} {primary_action}" pick up domain
        language without rewriting the prompt per domain.
        """
        return text.format(
            domain_name=self.name,
            display_name=self.display_name,
            description=self.description,
            user_role=self.user_role,
            entity_type=self.entity_type,
            primary_action=self.primary_action,
        )


_DOMAIN: Domain | None = None


def _interpolate_env(value: Any) -> Any:
    """Recursively replace ${VAR} and ${VAR:default} in YAML values."""
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    if isinstance(value, str):

        def sub(match: re.Match[str]) -> str:
            expr = match.group(1)
            if ":" in expr:
                name, default = expr.split(":", 1)
                return os.environ.get(name, default)
            return os.environ.get(expr, "")

        return re.sub(r"\$\{([^}]+)\}", sub, value)
    return value


def load_domain(spec_path: str | None = None) -> Domain:
    """Load and cache the active domain.

    Resolution order for the spec path:
      1. Explicit `spec_path` argument
      2. `COCO_DOMAIN_SPEC` env var (absolute or repo-relative)
      3. `COCO_DOMAIN` env var resolved to `domains/<name>/domain.yaml`
      4. Fallback: `domains/healthcare/domain.yaml` (the reference)
    """
    global _DOMAIN
    if _DOMAIN is not None and spec_path is None:
        return _DOMAIN

    if spec_path is None:
        spec_path = os.environ.get("COCO_DOMAIN_SPEC", "")
        if not spec_path:
            domain_name = os.environ.get("COCO_DOMAIN", "healthcare")
            spec_path = f"domains/{domain_name}/domain.yaml"

    path = Path(spec_path)
    if not path.is_absolute():
        # Try relative to repo root (cwd or COCO_REPO_ROOT)
        repo_root = Path(os.environ.get("COCO_REPO_ROOT", os.getcwd()))
        candidate = repo_root / path
        if candidate.exists():
            path = candidate
        else:
            # Try relative to this module's repo root
            here = Path(__file__).resolve().parent.parent.parent
            if (here / path).exists():
                path = here / path

    if not path.exists():
        raise FileNotFoundError(
            f"Domain spec not found at {path}. Set COCO_DOMAIN to a "
            f"directory under domains/ or COCO_DOMAIN_SPEC to an "
            f"absolute path."
        )

    logger.info("Loading domain spec from %s", path)
    raw = yaml.safe_load(path.read_text())
    raw = _interpolate_env(raw)

    d = raw.get("domain", {})
    voc = raw.get("vocabulary", {})
    data = raw.get("data", {})
    ont = raw.get("ontology", {})
    kn = raw.get("knowledge", {})
    sg = raw.get("sql_guardrails", {})
    ev = raw.get("evaluation", {})

    tables = [
        DomainTable(
            name=t["name"],
            description=t.get("description", ""),
            primary_key=t.get("primary_key", ""),
            foreign_keys=t.get("foreign_keys", {}),
        )
        for t in data.get("tables", [])
    ]

    domain = Domain(
        name=d.get("name", "unnamed_domain"),
        display_name=d.get("display_name", d.get("name", "")),
        description=d.get("description", ""),
        user_role=voc.get("user_role", "user"),
        entity_type=voc.get("entity_type", "entity"),
        primary_action=voc.get("primary_action", "answer questions"),
        data_mode=data.get("mode", "existing_uc_schema"),
        synthetic_generator=data.get("synthetic_generator", ""),
        tables=tables,
        ontology=DomainOntology(
            tool_name=ont.get("tool_name", "identify_entities"),
            tool_description=ont.get("tool_description", ""),
            index_name=ont.get("source", {}).get("index_name", ""),
            text_column=ont.get("source", {}).get("text_column", "content"),
            primary_key=ont.get("source", {}).get("primary_key", "chunk_id"),
            top_k=ont.get("source", {}).get("top_k", 5),
        ),
        knowledge=DomainKnowledge(
            source_volume_path=kn.get("source_volume_path", ""),
            chunk_size_tokens=kn.get("chunk_size_tokens", 512),
            chunk_overlap_tokens=kn.get("chunk_overlap_tokens", 50),
        ),
        sql_guardrails=DomainSqlGuardrails(
            allowed_schemas=sg.get("allowed_schemas", []),
            blocked_keywords=sg.get("blocked_keywords", []),
        ),
        evaluation_golden_set_path=ev.get("golden_set_path", ""),
        spec_path=str(path),
    )
    _DOMAIN = domain
    logger.info(
        "Domain loaded: name=%s tables=%d ontology_tool=%s",
        domain.name,
        len(domain.tables),
        domain.ontology.tool_name,
    )
    return domain


def get_domain() -> Domain:
    """Return the cached domain (load it if not yet loaded)."""
    return _DOMAIN if _DOMAIN is not None else load_domain()


def reset_domain_cache() -> None:
    """Test hook."""
    global _DOMAIN
    _DOMAIN = None
