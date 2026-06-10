# Forking CoCo for your domain

CoCo is designed to be forked. The healthcare cohort use case is just one
domain spec applied to a generic agent. To stand up the same agent for a
different domain (marketplace listings, legal codes, manufacturing parts,
HR analytics, etc.), you change a config file and point at your data. No
code changes for most domains.

This guide walks through the end-to-end fork.

## What you'll have at the end

A working CoCo deployment in your own Databricks workspace where the
agent answers natural language questions about YOUR data, with YOUR
domain vocabulary, your guardrails, and your knowledge corpus. Same
streaming UI, same observability, same cost attribution.

## What gets customized vs. what stays the same

| Stays the same | You customize |
|---|---|
| Agent loop (DSPy ReAct + ResponsesAgent wrapper) | Domain spec YAML |
| Apps frontend (FastAPI + HTMX) | Tables the agent queries |
| Lakebase session state schema | Ontology lookup tool name + description |
| 4-layer cost attribution | Knowledge corpus path |
| Per-user `unique_id` bundle namespacing | System prompt vocabulary |
| MLflow trace + judge.align flow | SQL guardrail allowed schemas |
| OBO auth pattern | Eval golden set |
| AI Search hybrid retrieval | (For non-healthcare) data generation step |

## Step 1: Clone the repo

```
gh repo clone debu-sinha/coco-reference your-domain-coco
cd your-domain-coco
```

## Step 2: Pick a domain name and write your domain.yaml

```
mkdir -p domains/your-domain
cp domains/healthcare/domain.yaml domains/your-domain/domain.yaml
```

Edit `domains/your-domain/domain.yaml`. The four most important fields:

### 2a. Tell the agent what your domain is

```yaml
domain:
  name: "your_domain"
  display_name: "Your Domain Assistant"
  description: >
    One paragraph the LLM reads to understand what kind of questions
    it should answer.

vocabulary:
  user_role: "who uses this (analyst, operator, clinician, etc.)"
  entity_type: "the thing the agent finds (cohort, listing, contract, etc.)"
  primary_action: "what they're trying to do (build a query, find a match, etc.)"
```

The agent's system prompt is templated with these. The same prompt code
runs for every domain because the words come from here.

### 2b. List the tables your agent will query

```yaml
data:
  mode: "existing_uc_schema"  # most forks use this
  tables:
    - name: "your_table_1"
      description: "What's in this table"
      primary_key: "id"
    - name: "your_table_2"
      description: "What's in this table"
      primary_key: "id"
      foreign_keys:
        your_table_1_id: "your_table_1"
```

The agent's `inspect_schema` tool reads this list and probes each table
via the UC metadata API at run time. Tables not listed here are invisible
to the agent.

Two `data.mode` values are supported:

- `existing_uc_schema` (recommended for most forks): the agent points at
  a UC schema you already populated. You provide the catalog and schema
  name via the bundle variables (see Step 4).
- `synthetic`: only the healthcare reference ships a synthetic data
  generator. For other domains, build your own loader notebook that
  writes to the same schema before deploying.

### 2c. Configure the ontology lookup tool

The agent has one domain-specific tool that maps user phrasing to canonical
codes or IDs. For healthcare this is the ICD-10 code lookup. For your
domain it might be a product taxonomy lookup, a statute code lookup, or a
part-number normalizer.

```yaml
ontology:
  tool_name: "lookup_your_thing"  # shown to the LLM as the tool name
  tool_description: >
    Map a user phrase like "X" to the canonical codes that your
    tables use (Y, Z). Tell the LLM when to call this.
  source:
    type: "vector_search"
    index_name: "${COCO_CATALOG_NAME}.${COCO_SCHEMA_NAME}.your_ontology_idx"
    text_column: "content"
    primary_key: "chunk_id"
    top_k: 5
```

### 2d. Point at your knowledge corpus

```yaml
knowledge:
  source_volume_path: "/Volumes/${COCO_CATALOG_NAME}/${COCO_SCHEMA_NAME}/your_knowledge"
  chunk_size_tokens: 512
  chunk_overlap_tokens: 50
```

Drop your reference docs (PDFs, markdown, txt) at that Volume path. The
setup notebook reads from there, chunks, and writes to the Vector Search
index.

## Step 3: Load your data into the UC schema

For `data.mode=existing_uc_schema`, you provide the data. Write a one-off
notebook or a DAB pipeline that creates the schema and writes your tables.
The table names must match what you put in `domain.yaml` under `data.tables`.

```python
# example: load your data into the target schema
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
df_listings.write.format("delta").saveAsTable(f"{catalog}.{schema}.listings")
df_dealers.write.format("delta").saveAsTable(f"{catalog}.{schema}.dealers")
```

For `data.mode=synthetic`, the healthcare reference is the example. To
build your own synthetic generator, look at `src/coco/data_generator/`
and write the equivalent for your domain.

## Step 4: Drop your knowledge docs into the Volume

```python
volume_path = f"/Volumes/{catalog}/{schema}/your_knowledge"
dbutils.fs.cp("file:/local/path/to/docs/", f"dbfs:{volume_path}/", recurse=True)
```

The setup notebook chunks anything in that path and writes to the Vector
Search index named by your `ontology.source.index_name`.

## Step 5: Deploy

```
python scripts/preflight_check.py --profile your-profile \
  --warehouse-id <your_serverless_wh> --unique-id your-id

databricks bundle deploy -t demo -p your-profile \
  --var unique_id=your-id \
  --var warehouse_id=<your_serverless_wh> \
  --var catalog=<your_catalog> \
  --var domain=your-domain

databricks bundle run setup_workspace -t demo -p your-profile \
  --var unique_id=your-id \
  --var warehouse_id=<your_serverless_wh> \
  --var catalog=<your_catalog> \
  --var domain=your-domain
```

The `--var domain=your-domain` selects `domains/your-domain/domain.yaml`.

## Step 6: Test it

Open the app URL printed at the end of the setup job and ask one of
your domain's representative questions. The agent should:

1. Call `inspect_schema` and list YOUR tables
2. Call your domain's ontology tool to look up codes
3. Generate SQL against YOUR schema
4. Run the SQL and return real results

If `inspect_schema` returns no tables, your domain spec table list does
not match what's in the UC schema. If the ontology tool returns nothing,
the VS index does not have your corpus indexed. The Risks section of the
main README has the diagnostic queries.

## Step 7: Iterate

The agent quality depends on three things you own:

1. **Your golden eval set.** 50 to 100 representative questions with
   ground-truth answers. Lives at the path in `evaluation.golden_set_path`.
   The eval notebook (02_evaluate.py) reads from here.

2. **Your prompts.** The defaults in `src/coco/agent/prompts/` use
   placeholders that pick up your domain vocabulary. If your domain has
   strong stylistic conventions (legalese, clinical terseness, etc.),
   register custom prompts via the MLflow Prompt Registry; the agent
   reads from there in production and falls back to your domain-templated
   defaults.

3. **Your knowledge corpus quality.** RAG quality is bottlenecked by
   chunking and source quality. Tune `chunk_size_tokens` and
   `chunk_overlap_tokens` in your domain spec against your golden eval.

## A worked example

`domains/retail-marketplace/domain.yaml` is a fully filled-out spec
for a marketplace use case (think RV listings, car listings, real
estate). It uses `data.mode=existing_uc_schema` so the forker brings
their own tables. Read it side-by-side with `domains/healthcare/domain.yaml`
to see what changes between domains.

## What you do NOT have to touch

- `src/coco/agent/responses_agent.py` (the agent loop)
- `src/coco/agent/tools/schema_inspector.py` (reads `domain.tables` automatically)
- `src/coco/agent/tools/sql_executor.py` (uses `domain.sql_guardrails`)
- `src/coco/app/` (the FastAPI frontend)
- `src/coco/observability/` (cost attribution)
- `databricks.yml` (bundle structure)

If you find yourself editing any of these to make your domain work,
that's usually a signal the abstraction should be lifted into
`domain.yaml`. File an issue or send a PR.

## Troubleshooting

- **Agent says "no tables found"**: your domain spec table list does
  not match the real UC schema. Compare `domain.data.tables[].name`
  against `SHOW TABLES IN your_catalog.your_schema`.
- **Agent uses healthcare language despite a different domain**:
  prompts are still the registered healthcare versions. Either delete
  the registered prompt versions in UC so the agent falls back to the
  templated defaults, or register your own.
- **Ontology tool returns nothing**: the VS index is empty. Re-run the
  knowledge corpus chunking step in the setup notebook with your docs
  in place at `knowledge.source_volume_path`.
- **SQL execution returns PermissionDenied**: the served-entity SP needs
  workspace entitlements. The setup notebook handles this automatically
  per the fixes already in the repo (see the OBO commit).

## Reference

- Reference healthcare domain: `domains/healthcare/domain.yaml`
- Reference marketplace domain: `domains/retail-marketplace/domain.yaml`
- Domain loader: `src/coco/domain.py`
- Original CoCo architecture: `docs/ARCHITECTURE.md`
