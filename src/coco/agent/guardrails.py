"""SQL execution guardrails and validation.

Two layers of defense against runaway or unsafe SQL reaching the
warehouse:

1. Read-only enforcement — reject any statement containing
   DML/DDL keywords (DROP, UPDATE, DELETE, INSERT, ALTER, CREATE,
   TRUNCATE, MERGE, REPLACE, GRANT, REVOKE).

2. Schema allowlist — every fully-qualified three-part identifier
   (`catalog.schema.table`) must resolve to one of the allowed
   schemas in `config.guardrails.allowed_schemas`. Bare identifiers
   and two-part identifiers are allowed through: they're either CTE
   aliases, local tables, or subquery references, none of which are
   meaningful for schema gating.

The second layer is the primary PHI/PII boundary alongside the
Gateway-level filters: even if the agent's SQL generator drifts, it
can't reach data outside the workshop catalog.
"""

from __future__ import annotations

import logging
import re

from coco.config import get_config

logger = logging.getLogger(__name__)

_DANGEROUS_KEYWORDS = (
    "DROP",
    "UPDATE",
    "DELETE",
    "INSERT",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "MERGE",
    "REPLACE",
    "GRANT",
    "REVOKE",
)

# Capture three-part dotted identifiers: catalog.schema.table (no quotes
# or backtick-quoted). This is the form the agent is instructed to emit.
_THREE_PART_IDENT = re.compile(
    r"\b(`?[A-Za-z_][A-Za-z0-9_]*`?)"
    r"\.(`?[A-Za-z_][A-Za-z0-9_]*`?)"
    r"\.(`?[A-Za-z_][A-Za-z0-9_]*`?)\b"
)

# Strip SQL comments before keyword scanning so a line like
# `SELECT 1 -- DROP TABLE` doesn't trip the keyword check.
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# Nested block comments (non-standard but some engines support them).
# We strip iteratively in _strip_noise so `/* /* DROP */ */` collapses.
_BLOCK_COMMENT_OUTER = _BLOCK_COMMENT
# Strip string literals so embedded keywords like 'DROP THE BASS' don't
# trip either.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_noise(sql: str) -> str:
    """Remove comments and string literals before keyword scanning.

    Block comments are stripped iteratively to handle nesting like
    ``/* outer /* DROP TABLE x */ still inside */``.
    """
    # Iteratively strip block comments so nested pairs collapse fully.
    prev = None
    clean = sql
    while prev != clean:
        prev = clean
        clean = _BLOCK_COMMENT.sub(" ", clean)
    no_line = _LINE_COMMENT.sub(" ", clean)
    no_strings = _STRING_LITERAL.sub(" ", no_line)
    return no_strings


def validate_sql_query(sql: str) -> tuple[bool, str]:
    """Validate SQL against the workshop guardrails.

    Returns:
        (is_valid, reason) — reason is empty on success.
    """
    try:
        config = get_config()
        guardrails = config.guardrails

        if not sql or not sql.strip():
            return False, "Empty SQL"

        clean = _strip_noise(sql)
        upper = clean.upper()

        # 1. Read-only keyword check
        if guardrails.sql_read_only:
            for keyword in _DANGEROUS_KEYWORDS:
                if re.search(rf"\b{keyword}\b", upper):
                    return (
                        False,
                        f"Guardrail violation: {keyword} not allowed in read-only mode",
                    )

        # 2. Schema allowlist check — only applies to fully-qualified
        # three-part identifiers.
        allowed = set(guardrails.allowed_schemas)
        for match in _THREE_PART_IDENT.finditer(clean):
            catalog = match.group(1).strip("`")
            schema = match.group(2).strip("`")
            table = match.group(3).strip("`")
            # Block identifiers with special chars that could bypass
            # the allowlist via encoding tricks.
            for part_name, part_val in [
                ("catalog", catalog),
                ("schema", schema),
                ("table", table),
            ]:
                if not _SAFE_IDENT.match(part_val):
                    return (
                        False,
                        f"Invalid {part_name} identifier: '{part_val}' "
                        f"(expected [A-Za-z0-9_] characters)",
                    )
            qualified_schema = f"{catalog}.{schema}"
            if qualified_schema not in allowed:
                return (
                    False,
                    f"Schema '{qualified_schema}' not in allowed list: {sorted(allowed)}",
                )

        return True, ""

    except Exception as e:
        logger.error("SQL validation error: %s", e)
        return False, f"Validation error: {e}"
