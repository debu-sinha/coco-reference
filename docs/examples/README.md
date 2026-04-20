# Examples

Short self-contained examples for patterns that come up in CoCo v2
and in adjacent customer conversations. Each file is runnable by
itself and should not depend on the rest of the coco-reference repo
beyond standard pip packages.

## `databricks_hosted_claude_for_dspy.py`

How to call `databricks-claude-sonnet-4-5` (or any Databricks Model
Serving endpoint) from outside Databricks, specifically from a DSPy
module that currently uses enterprise OpenAI.

Three patterns in the same file:

1. **Raw httpx** - baseline to confirm the PAT, endpoint name, and
   CAN_QUERY ACL are correct
2. **OpenAI SDK** - one-line swap if your existing code already uses
   `openai.OpenAI`
3. **DSPy** - `dspy.LM("databricks/databricks-claude-sonnet-4-5", ...)`
   drop-in for DSPy 2.5+

Run with:

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."                  # your PAT
# optional override
export DATABRICKS_SERVING_ENDPOINT="databricks-claude-sonnet-4-5"

python docs/examples/databricks_hosted_claude_for_dspy.py httpx
python docs/examples/databricks_hosted_claude_for_dspy.py openai
python docs/examples/databricks_hosted_claude_for_dspy.py dspy
```

### What auth you actually need

There is no special `serving.*` scope on the PAT itself. A regular
Databricks PAT is a bearer token, and the endpoint's **CAN_QUERY**
permission is what gates the call.

1. Mint a PAT (UI: User Settings -> Developer -> Access tokens, or
   via the CLI / SDK)
2. Grant your user or service principal `CAN_QUERY` on the target
   serving endpoint (UI: Machine Learning -> Serving -> endpoint ->
   Permissions)

That's the entire scope story. If you've been struggling to get
hosted models working from a remote DSPy module, the missing piece
is almost certainly the CAN_QUERY grant on the endpoint, not the
token itself.

### Why bother moving from enterprise OpenAI / Anthropic direct?

Five reasons, any one of which alone justifies the switch for a
healthcare data team:

1. **BAA coverage**. Databricks is a business associate under your
   existing BAA. Anthropic direct / OpenAI direct is a new
   processor - new BAA, new DPA, new vendor risk review, new DPO
   sign-off, new data-flow map updates. Moving model calls
   inside Databricks keeps PHI within an existing signed BAA.
2. **Data locality**. The model call runs inside the Databricks
   workspace boundary. Your DSPy module can pull reference data
   from Unity Catalog, build a prompt, call the model, and get a
   response without the cohort context ever leaving the platform.
   Going direct marshalls context across an external API boundary
   on every call.
3. **Unity Catalog row and column level permissions flow through**
   when you call via the user's OBO path (or via a scoped SP).
   Going direct, the model has no UC identity and you have to
   rebuild access control at the prompt-construction layer - and
   good luck getting Legal to sign off on a custom PHI auth path.
4. **Mosaic AI Gateway in front of the endpoint** gives you rate
   limits, PII filters, safety filters, request/response caching,
   fallback routing, and per-call audit logging - none of which you
   get on the direct-API paths out of the box.
5. **Cost attribution in `system.billing`**. Databricks-hosted model
   calls show up in `system.billing` with the same workload tagging
   as every other Databricks cost source. You can tag by cluster,
   by workload, by user, by cohort, whatever you want. Direct API
   calls land on a separate invoice in a separate silo with no way
   to unify the story. If you're building a per-workload cost
   model for your AI workloads, you need the calls inside the
   Databricks billing boundary - full stop.

### Why the file lives in coco-reference

Customer teams evaluating DSPy often ask how to call Databricks-
hosted models from DSPy running outside Databricks (local scripts,
external services). This file is the canonical answer, placed next
to the reference implementation so readers can compare a "DSPy
client talking to Databricks models" setup against the full
Databricks App + Mosaic AI Agent Framework pattern in the rest of
this repo.
