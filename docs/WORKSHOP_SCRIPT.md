# CoCo v2 Workshop Runbook

**Duration:** 2 hours (30 min demo + 90 min hands-on)

**Audience:** Databricks healthcare customers, data engineers, clinical informatics teams

**Objective:** Demonstrate how AI agents reduce time to insights for healthcare RWD queries.

---

## Pre-Workshop Checklist (1 hour before)

- [ ] Workspace provisioned (run `notebooks/00_setup_workspace.py`)
- [ ] FastAPI app deployed (`databricks bundle deploy -t demo`)
- [ ] SQL Warehouse warmed up (run a test query)
- [ ] Model Serving endpoint warm (invoke agent once)
- [ ] Share app URL with attendees
- [ ] Have backup demo video (if internet fails)

---

## Part 1: Demo (30 minutes)

### Slide 1: Title + Agenda (2 min)

"**CoCo: AI Cohort Copilot for Real-World Data**"

> We're going to show you how to answer clinical questions in seconds instead of hours.

**Agenda:**
- What is CoCo?
- Live demo (5 minutes)
- Under the hood (5 minutes)
- Q&A (3 minutes)

### Slide 2: Problem Statement (3 min)

"**The RWD Query Challenge**"

Typical workflow for cohort queries today:
1. Clinical team: "Find Type 2 diabetes patients on metformin with recent HbA1c labs"
2. Data team: Draft SQL, validate with clinical colleagues
3. Back-and-forth: "Actually, include hypertension too" -> modify SQL
4. **Time: 2-8 hours** 

**Cost:**
- Data engineer time (senior, $150/hr)
- Delayed insights (impact on care)
- Bottleneck for exploratory analysis

### Slide 3: The Solution (2 min)

"**CoCo: Natural Language -> Validated SQL -> Results**"

The happy path in one breath:

1. User types: `Type 2 diabetes patients on metformin`
2. `dspy.ReAct` picks `identify_clinical_codes` -> returns `E11.9`
3. `dspy.ReAct` picks `generate_sql` -> returns a `SELECT ... FROM diagnoses JOIN prescriptions WHERE code='E11.9' AND drug='metformin'`
4. `dspy.ReAct` picks `execute_sql` -> guardrails validate, the warehouse runs it, 42 rows return
5. The agent's `finish` action renders the answer; the App streams it back to the browser

See `docs/design/diagrams/request-flow.svg` for the full architecture.

**Key features:**
- No SQL needed
- Guardrails prevent harmful queries
- Streams results in real-time
- Learns from feedback

### Live Demo (15 min)

**Setup:**
- Open app at `[URL from setup_complete.json]`
- Create new thread: "Clinical Cohort Analysis"

**Query 1: Simple (2 min)**
- Input: "Find patients with Type 2 diabetes"
- Show:
  - "Thinking..." message
  - Code identification (E11.9)
  - SQL generation
  - Results streaming in
  - Sample rows displayed
- Output: "Found 2,847 Type 2 diabetes patients"

**Query 2: Complex (3 min)**
- Input: "Type 2 diabetes patients on metformin with HbA1c over 8% in the last 30 days"
- Show:
  - Multi-step planning (code identification -> SQL -> execution)
  - Multiple JOINs in generated SQL
  - Subqueries for date filtering
- Output: "Found 312 patients with suboptimal control"

**Query 3: Follow-up (2 min)**
- Input: "Now add hypertension as a requirement"
- Show:
  - Conversational refinement (uses prior context)
  - Adjusted SQL
  - Reduced results (312 -> 87)
- Highlight: No need to re-query from scratch

**Rate Response (2 min)**
- Click thumbs-up on one response
- Explain: Feedback trains the model

**Q from audience:** "What if the SQL is wrong?"
- Answer: "Let's look at it" -> click "Show SQL"
- Explain guardrails: read-only, schema whitelist

### Slide 4: Under the Hood (5 min)

**Architecture diagram:**

![CoCo request flow](design/diagrams/request-flow.svg)

**Key innovations:**
1. **dspy.ReAct with native tool calling** - the model picks tools from Python function signatures, no keyword-matched planner (see `src/coco/agent/responses_agent.py`, `MAX_ITERS=7`)
2. **Clinical codes** - `identify_clinical_codes` tool returns ICD-10/NDC codes with rationale
3. **SQL generation + guardrails** - `generate_sql` produces Databricks SQL, `execute_sql` validates read-only + schema allowlist before running
4. **Streaming** - Server-sent events chunk the answer to the browser while the agent runs
5. **Feedback loop** - Thumbs up/down drives weekly GEPA optimization via `mlflow.genai.optimize_prompts`

**Prompt optimization:**
- Show 03_optimize_dspy.py concept
- "Every thumbs-up refines our prompts"

### Slide 5: Q&A (3 min)

Common Q&A:

**Q: Can it hallucinate SQL?**
A: Yes, sometimes. That's why we show the SQL and have guardrails. If it's wrong, you see it and can refine.

**Q: Does it work with other data sources?**
A: CoCo is built for Databricks RWD. It could be adapted to Teradata, other DWs, but requires schema mapping.

**Q: What about HIPAA/compliance?**
A: Guardrails block sensitive queries. Gateway-level filters block PII in prompts. Audit trail via MLflow.

**Q: How much does it cost?**
A: Pay for compute: SQL Warehouse, Model Serving endpoint. ~$10-20/month for demo scale (10k patients, light usage).

---

## Part 2: Hands-On Lab (90 minutes)

**Goal:** Attendees build a custom tool or extend CoCo.

### Setup (10 min)

1. **Provide each attendee:**
   - GitHub repo link (coco-reference)
   - Databricks workspace URL
   - Pre-filled workspace config

2. **Clone repo:**
   ```bash
   git clone <repo-url>
   cd coco-reference
   ```

3. **Test local setup:**
   ```bash
   export COCO_CONFIG_PATH=config/default.yaml
   pytest -m unit --tb=short
   ```

### Lab 1: Add a New Tool (30 min)

**Objective:** Add a "PatientCount" tool that returns count for a diagnosis code.

**Steps:**

1. **Read existing tool:**
   ```bash
   cat src/coco/agent/tools/clinical_codes.py
   ```

2. **Create new tool:**
   ```bash
   cp src/coco/agent/tools/clinical_codes.py src/coco/agent/tools/patient_count.py
   ```

3. **Edit patient_count.py:**
   - Change `ClinicalCodeSignature` to `PatientCountSignature`
   - Input: diagnosis code (e.g., "E11.9")
   - Output: count of patients with that code
   - Call SQL executor instead of LLM

4. **Write test:**
   ```bash
   cat > tests/unit/test_patient_count.py << 'EOF'
   import pytest
   from coco.agent.tools.patient_count import patient_count

   @pytest.mark.unit
   def test_count_returns_int():
       result = patient_count("E11.9")
       assert isinstance(result, int)
       assert result >= 0
   EOF
   ```

5. **Run test:**
   ```bash
   pytest tests/unit/test_patient_count.py -v
   ```

6. **Integrate into agent:**
   - Edit `src/coco/agent/responses_agent.py`
   - Add to tool registry
   - Test: "How many Type 2 diabetes patients do we have?"

### Lab 2: Customize Evaluation Scenarios (30 min)

**Objective:** Create evaluation scenarios for your use case.

**Steps:**

1. **Review scenarios:**
   ```bash
   cat evaluation/scenarios.yaml | head -30
   ```

2. **Add custom scenarios:**
   ```bash
   cat >> evaluation/scenarios.yaml << 'EOF'
   - id: my_hospital_cohort
     category: custom
     difficulty: medium
     query: "Heart failure patients admitted in last 30 days"
     expected_tables:
       - diagnoses
       - procedures
     expected_codes:
       - code: I50.9
         type: ICD-10
   EOF
   ```

3. **Run evaluation:**
   Open `notebooks/02_evaluate.py` in the workspace and run it as a
   job (or interactively). It invokes the live agent endpoint via
   `mlflow.genai.evaluate` and scores each scenario against the
   scorers defined in `src/coco/observability/scorers.py`.

4. **Interpret results:**
   - View JSON output
   - Check SQL validity score
   - Check clinical accuracy
   - Refine scenario if needed

### Lab 3: Optimize Prompts (30 min)

**Objective:** Improve model performance using feedback.

**Steps:**

1. **Understand the GEPA optimization loop:**
   - Read: `notebooks/03_optimize_dspy.py`
   - Core API: `mlflow.genai.optimize_prompts` with `GepaPromptOptimizer`
   - Concept: thumbs-up feedback in Lakebase -> evolutionary prompt search -> new registered version -> production alias flip

2. **Simulate feedback loop:**
   ```bash
   # Trigger the optimize job via the bundle:
   databricks bundle run optimize_dspy -t demo -p PROFILE \
     --var unique_id=YOUR_ID --var catalog=CATALOG
   ```

3. **Interpret results:**
   - Check the MLflow run for the optimize_prompts artifact (`optimized_template.txt`)
   - Compare eval metrics before vs. after via `run_evaluation` job
   - Expected: GEPA can regress on small feedback samples. If eval metrics drop, roll back with `mlflow.genai.set_prompt_alias(name=..., version=<prev>, alias="production")` - no redeploy needed.

4. **(Optional) Fine-tune scorer choice:**
   ```python
   # Swap the built-in Correctness scorer for a domain-specific one
   # in notebooks/03_optimize_dspy.py:
   #   scorers=[MyCustomScorer(...)]
   ```

---

## Workshop Troubleshooting

### "App URL doesn't work"
- Check: `setup_complete.json` for correct URL
- Verify: Endpoint is running (`databricks bundle get-summary -t demo`)
- Restart: `databricks apps delete coco-app`, then redeploy

### "SQL Warehouse timing out"
- Check warehouse is running
- Increase timeout in `config/default.yaml`: `wait_timeout: "60s"`
- Reduce query complexity for demo

### "Model Serving endpoint is cold"
- Pre-warm 5 min before demo: Make a test request
- Or disable scale-to-zero in `databricks.yml` during workshop

### "Network issues / No internet"
- Have offline demo video ready
- Screenshots of expected outputs
- Have an offline backup - a screenshot walk-through of notebook 02
  output + MLflow eval run - so attendees can still follow the flow.

---

## Takeaways (Slide at end)

1. **AI agents accelerate RWD analysis** - from hours to seconds
2. **Guardrails make LLMs safe for healthcare** - read-only, schema whitelist, audit trails
3. **Feedback improves performance** - model learns from your data and use cases
4. **Open source means customizable** - add your own tools, evaluation metrics, prompts

**Next steps for your org:**
- Clone the repo
- Deploy to your workspace (docs/DEPLOYMENT.md)
- Add your RWD schema
- Optimize prompts for your clinical questions
- Integrate into your analytics platform

---

## Follow-Up

**Post-workshop resources:**
- `README.md` - Full project overview
- `docs/ARCHITECTURE.md` - Deep dive on design
- `docs/DEPLOYMENT.md` - Production deployment guide
- `tests/README.md` - Testing setup
- GitHub issues - Questions & bugs

**Contact:**
- engineering@databricks.com
- Slack: #coco-agent
- Repo: [github.com/debu-sinha/coco-reference](https://github.com/debu-sinha/coco-reference)
