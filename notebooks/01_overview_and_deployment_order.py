# Databricks notebook source
# MAGIC %md
# MAGIC # CoCo Overview and Deployment Order
# MAGIC
# MAGIC New here? Start with this notebook. It walks you through every
# MAGIC component CoCo deploys, in the order they have to come up, and
# MAGIC what to verify at each step.
# MAGIC
# MAGIC You should be able to read this top to bottom in 10 minutes and
# MAGIC then run the rest of the workshop with a clear mental model of
# MAGIC what is happening.
# MAGIC
# MAGIC ## Who this is for
# MAGIC
# MAGIC - You have a Databricks workspace and CLI installed.
# MAGIC - You have not built an agentic application on Databricks before.
# MAGIC - You want to understand what gets deployed and why, not just run
# MAGIC   the commands.

# COMMAND ----------
# MAGIC %md
# MAGIC ## What CoCo is, in one paragraph
# MAGIC
# MAGIC CoCo is a chat-style agent that answers natural language questions
# MAGIC about your data. The reference domain ships with healthcare cohort
# MAGIC analysis ("How many patients are on metformin with recent labs?"),
# MAGIC but the same agent runs against any domain by swapping a single
# MAGIC YAML config file. The repo bundles a working UI, the agent itself,
# MAGIC retrieval, evaluation, cost tracking, and the deployment automation
# MAGIC into one workshop you can deploy in about 30 minutes.

# COMMAND ----------
# MAGIC %md
# MAGIC ## The architecture in one paragraph
# MAGIC
# MAGIC A user types a question in a small web UI that runs as a Databricks
# MAGIC App (FastAPI + HTMX). The App forwards the question to an agent
# MAGIC running on Model Serving, where a DSPy ReAct loop wrapped by
# MAGIC MLflow's ResponsesAgent uses three tools: look up domain entities,
# MAGIC generate SQL, and execute SQL. The agent calls the Claude Sonnet
# MAGIC LLM via the Foundation Model API behind Unity AI Gateway, reads
# MAGIC table metadata via Unity Catalog, retrieves context from an AI
# MAGIC Search index, stores conversation state in Lakebase, and logs
# MAGIC every step to MLflow Traces for observability and judge alignment.

# COMMAND ----------
# MAGIC %md
# MAGIC ## What gets deployed and in what order
# MAGIC
# MAGIC There are seven things that have to come up, in a specific order,
# MAGIC because each one depends on the ones before it. The setup notebook
# MAGIC (`00_setup_workspace.py`) automates the whole sequence, but it
# MAGIC helps to know what each step is doing so you can debug if
# MAGIC something fails.
# MAGIC
# MAGIC | # | Component | Why this order | What it does | If this fails |
# MAGIC |---|---|---|---|---|
# MAGIC | 1 | Unity Catalog catalog + schema | Everything else lives in UC | Holds your tables, models, vector index, and registered prompts | You likely lack `CREATE SCHEMA` on the catalog. Ask an admin. |
# MAGIC | 2 | Data tables (synthetic or BYO) | Tables must exist before the agent can probe them | For healthcare: synthetic patients/diagnoses/etc. For other domains: you load your own. | Check `data.mode` in your `domain.yaml`. See `docs/FORK_GUIDE.md`. |
# MAGIC | 3 | Knowledge corpus in a UC Volume | The vector index reads from this Volume | Documents the agent retrieves at chat time (ICD codes for healthcare, product taxonomy for retail, etc.) | Verify the path in `domain.yaml` `knowledge.source_volume_path`. |
# MAGIC | 4 | Vector Search endpoint + index | The retrieval tool needs the index live | Built from the knowledge corpus. The agent's domain-entity tool queries this. | Endpoint creation can take 10 minutes on a cold workspace. Be patient. |
# MAGIC | 5 | Lakebase instance + database | The App needs somewhere to store chat threads | Postgres-backed session state for the chat UI | Lakebase is a preview feature. If unavailable in your workspace, set `--var minimal=true` to skip; sessions then live in memory and reset on App restart. |
# MAGIC | 6 | Agent on Model Serving | The App calls this | Logs the agent as an MLflow model, deploys to a serving endpoint, with both system + user auth policies for OBO | Check the endpoint state in the Model Serving UI. Most failures here are missing UC grants or wrong warehouse permissions. |
# MAGIC | 7 | Databricks App | The user-facing UI | A small FastAPI + HTMX site bound to the warehouse, agent endpoint, and Lakebase database via typed resources | The App container takes about 1 minute to start. Refresh if the URL 502s on first hit. |

# COMMAND ----------
# MAGIC %md
# MAGIC ## What each component looks like in your workspace
# MAGIC
# MAGIC After the setup notebook finishes, you can verify each piece is in
# MAGIC place. Click each link to inspect.

# COMMAND ----------

# Resolve these from the widgets in 00_setup_workspace.py or your bundle
# variables. The setup_complete.json file in the artifacts volume has
# the final values for your deploy.
catalog = "coco_demo"  # or your value
schema = "cohort_builder_<your_unique_id>"
host = "<your-workspace>.cloud.databricks.com"

print(f"Catalog and schema:    https://{host}/explore/data/{catalog}/{schema}")
print(f"Vector Search:         https://{host}/explore/vector-search")
print(f"Lakebase instance:     https://{host}/lakebase")
print(f"Model Serving:         https://{host}/ml/endpoints")
print("App URL:               check setup_complete.json or the Databricks App in the workspace UI")

# COMMAND ----------
# MAGIC %md
# MAGIC ## How to actually run the deployment
# MAGIC
# MAGIC The setup is a Databricks Asset Bundle. From your laptop:
# MAGIC
# MAGIC ```bash
# MAGIC # one-time check: confirm you have permissions and prereqs
# MAGIC python scripts/preflight_check.py --profile YOUR_PROFILE \
# MAGIC   --warehouse-id YOUR_WAREHOUSE_ID
# MAGIC
# MAGIC # deploy the bundle
# MAGIC databricks bundle deploy -t demo -p YOUR_PROFILE \
# MAGIC   --var unique_id=YOUR_INITIALS \
# MAGIC   --var warehouse_id=YOUR_WAREHOUSE_ID \
# MAGIC   --var catalog=YOUR_CATALOG \
# MAGIC   --var domain=healthcare        # or your domain folder under domains/
# MAGIC
# MAGIC # run the setup job that provisions everything in order
# MAGIC databricks bundle run setup_workspace -t demo -p YOUR_PROFILE \
# MAGIC   --var unique_id=YOUR_INITIALS \
# MAGIC   --var warehouse_id=YOUR_WAREHOUSE_ID \
# MAGIC   --var catalog=YOUR_CATALOG \
# MAGIC   --var domain=healthcare
# MAGIC ```
# MAGIC
# MAGIC The setup job runs notebook `00_setup_workspace.py`, which walks
# MAGIC the seven steps in the table above and reports as it goes.

# COMMAND ----------
# MAGIC %md
# MAGIC ## Where to look when something fails
# MAGIC
# MAGIC Most failures are visible in one of three places.
# MAGIC
# MAGIC 1. **Setup job run output**. Open the job link the bundle prints
# MAGIC    and scroll to the failed cell. Each step in the setup notebook
# MAGIC    prints what it is doing before it does it.
# MAGIC 2. **Model Serving endpoint UI**. The agent deploys here. If the
# MAGIC    endpoint is not READY, the UI shows the served entity state
# MAGIC    and the deployment error message verbatim.
# MAGIC 3. **App logs**. The Databricks App page has a Logs tab. If the
# MAGIC    UI loads but no agent reply comes back, this is where the
# MAGIC    error lives.
# MAGIC
# MAGIC The most common failure modes are documented in
# MAGIC `docs/FORK_GUIDE.md` under Troubleshooting.

# COMMAND ----------
# MAGIC %md
# MAGIC ## After this notebook
# MAGIC
# MAGIC 1. Run `scripts/preflight_check.py` to confirm your workspace is
# MAGIC    ready before you deploy.
# MAGIC 2. Open `domains/healthcare/domain.yaml` and read it. This is the
# MAGIC    one file you change to fork CoCo for your own domain.
# MAGIC 3. Run the bundle deploy and setup commands above.
# MAGIC 4. Open the App URL and ask "how many records in the patients table?"
# MAGIC    You should see real numbers come back inside ~30 seconds.
# MAGIC 5. To fork for a different domain, read `docs/FORK_GUIDE.md`. The
# MAGIC    only file you change for most domains is your new `domain.yaml`.
