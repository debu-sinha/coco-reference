# Security Posture and Limitations

CoCo v2 is a **reference implementation**, not a hardened production
build. This doc captures every security-relevant design decision and
the limits of each safeguard so you can evaluate the repo before
deploying it against real data. If something here doesn't match your
threat model, don't deploy.

If you find a vulnerability in this repo, open an issue or reach out
privately to the maintainer - don't disclose publicly until a fix
is in place.

## Identity and authentication

### What the repo assumes

- The app runs inside **Databricks Apps**, which fronts every
  request with its own authentication layer. The app container
  receives `X-Forwarded-Email` on every authenticated request.
- Data access is performed by the app's **service principal (SP)**,
  not the end user. The SP has scoped UC grants via typed resource
  bindings (warehouse `CAN_USE`, endpoint `CAN_QUERY`, Lakebase
  `CAN_CONNECT_AND_CREATE`). This is deliberate - on-behalf-of
  (OBO) user token passthrough is *not* used.

### What this means in practice

- Every row in Lakebase (`threads`, `messages`, `feedback`) is
  tagged with the user's email. Agent traces in MLflow carry the
  same tag. Audit questions like "what did Alice ask?" are
  answerable.
- Because the SP executes queries, Alice and Bob see the same data
  if both can access the app. **If your threat model needs
  row-level access differentiation between app users, you'll need
  an additional authorization layer** (UC row filters, a per-user
  session-scoped SQL warehouse, or OBO with `user_api_scopes`) -
  CoCo doesn't provide it out of the box.
- The `UserIdentity.access_token` field on every request is a
  placeholder string (`apps-sp`) in SP-only mode. It is **not**
  a usable credential; downstream code that expects a real token
  will fail, which is the intended behavior.

### Local development

`COCO_USER_ID` env var sets a stub identity for local dev. This
path is only reached when Databricks Apps headers are absent. In a
deployed environment it is unreachable.

## SQL safety

### Guardrails (`src/coco/agent/guardrails.py`)

Every SQL statement the agent generates flows through
`validate_sql_query()` before execution. The checks:

- **Read-only:** `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`,
  `CREATE`, `TRUNCATE`, `MERGE`, `GRANT`, `REVOKE`, and similar
  statements are rejected by substring and token match.
- **Schema allowlist:** the parsed statement must reference only
  tables under the configured `catalog.schema_*` allowlist from
  `config.guardrails.allowed_schemas`. Cross-schema joins are
  rejected.

### Known limits

- The guardrails are **defense in depth**, not the only line of
  defense. The primary protection is that the SP has `SELECT`-only
  grants on the allowed tables - even a bypass of `guardrails.py`
  cannot write or read outside those tables.
- The regex-based comment stripper may not cover every adversarial
  nesting pattern. Running untrusted user text through this pipeline
  is NOT the intended threat model. If your app exposes SQL
  generation to untrusted input, layer a proper SQL parser
  (sqlparse is already a dependency) and write fuzz tests for your
  specific attack surface.
- Quoted identifiers, CTE aliases, and subqueries are all accepted
  as valid SQL. The allowlist check looks for table references
  lexically; complex SQL that references an allowed table only via
  a CTE that wraps an underlying `information_schema` query will
  pass the check. Mitigation is the SP's UC grant - always grant
  the SP only the specific tables it needs to see.

## PHI / PII handling

### What the repo stores

- **Prompt text** (user messages) lands in:
  - MLflow traces (experiment: `/Users/<email>/coco-agent`)
  - Lakebase `coco_sessions.messages` table
  - Serving endpoint inference tables (if enabled - off by default)
- **SQL results** flow back to the user through the app and are
  rendered in the chat UI. They are also embedded in the agent's
  response text and stored in Lakebase + MLflow.
- **Clinical codes** (ICD-10, NDC, CPT) and **column values** from
  the RWD tables pass through the agent's LLM. Whatever your
  Foundation Model API provider logs (Databricks, Anthropic,
  OpenAI via Gateway) will see this content.

### What the repo does NOT do

- **No PHI redaction** before logging. MLflow traces and Lakebase
  rows contain the literal prompt text and SQL results.
- **No encryption at rest** beyond what Databricks / Lakebase /
  Delta provide by default.
- **No content-based PHI detection** at runtime. The
  `phi_leak_scorer` in `src/coco/observability/scorers.py` is an
  *evaluation* tool, not a runtime guard.

### Deploying against real PHI

You must satisfy at least all of these before pointing the app at
PHI-bearing tables:

1. Workspace Compliance Security Profile set to **HIPAA** and the
   relevant BAA executed with Databricks.
2. UC column-level masking applied to any column the agent should
   not see in plain text (SSN, full DOB, free-text notes).
3. A runtime content filter on agent responses (Mosaic AI Gateway
   has one - turn it on).
4. An MLflow trace retention policy matched to your PHI retention
   rules. Trace data is not automatically expired.
5. Review the Foundation Model API provider's BAA coverage for
   whichever endpoint is configured in `config.llm.endpoint`.

## Lakebase credentials

- Lakebase credentials are **short-lived OAuth tokens** (~1h TTL)
  minted on demand via the SDK. The app does NOT hold long-lived
  Postgres passwords.
- The token TTL is assumed to be 60 minutes with a 5-minute safety
  margin. If Databricks changes Lakebase credential lifetimes, the
  pool will rotate on the next observed auth-expiry error. See
  `src/coco/app/sessions/lakebase.py`.
- `PGPASSWORD` is never written to disk or logged. It lives only
  in process memory for the lifetime of the pool.

## Model Serving endpoint

- The agent serving endpoint (`coco-agent-<ns>`) inherits the
  workspace's Model Serving ACL model. Grant `CAN_QUERY` only to
  the app's SP; non-SP users should not hit the endpoint directly.
- The endpoint's `environment_vars` include
  `COCO_CATALOG_NAME` / `COCO_SCHEMA_NAME` / `COCO_WAREHOUSE_ID`.
  These are not secrets but they do reveal workspace topology -
  treat endpoint config as internal.

## MLflow Prompt Registry

- Prompts are UC-registered under
  `<catalog>.<schema>.<name>`. The `@production` alias determines
  which version the agent serves.
- Anyone with `MANAGE` on the prompt object can flip aliases and
  thereby change what the agent says without redeploying. Grant
  `MANAGE` carefully and audit alias flips.

## Threats this repo does NOT address

- **Prompt injection** through tool docstrings or ambient context
  (e.g., a row in a RAG table containing instructions like "ignore
  previous directions"). DSPy's tool calling does not validate
  tool descriptions. Curate your knowledge base.
- **Denial of service** from an attacker forcing many expensive
  LLM calls. Rate limiting exists at the app layer
  (`src/coco/app/main.py`) but is not tuned for adversarial
  traffic. Front the app with a WAF if exposed to untrusted users.
- **Data exfiltration** via a crafted SQL query that reads a lot
  of rows and renders them in a prompt that the LLM then echoes
  out. The SP's read-only, schema-scoped UC grants + response size
  limits in the app mitigate but do not eliminate this.
- **Supply chain attacks** on the Python dependencies. The repo
  pins major versions in `pyproject.toml` and notebook `%pip`
  lines but does not freeze exact versions or verify hashes. Run
  `pip-audit` or your vulnerability scanner of choice before
  production deploys.

## Reporting

Security questions or concerns: open a GitHub issue tagged
`security`, or contact the maintainer listed in the repo README.
Public disclosure after a fix ships is the preferred flow.
