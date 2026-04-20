# Tagging and Attribution Policy (Draft)

A short, opinionated policy for wiring per-workload cost visibility
into a Databricks deployment. This is a reference starting point -
adapt the tag values and enforcement posture to match your existing
operational model. The shape of the policy is what matters, not the
specific names.

## Principle: every compute carries the same four tags

Every cluster, SQL warehouse, serving endpoint, and job launched in
the workspace MUST carry these four tags at creation time:

| Tag         | Example value        | Why |
|-------------|----------------------|-----|
| `workload`  | `coco`, `ehr_etl`    | the named workload, used for chargeback and for the "how much did X cost" view |
| `team`      | `rwds`               | the owning team, used for rollups across workloads |
| `env`       | `dev`, `stg`, `prd`  | separates prod spend from experimentation so dev regressions do not blow the prod budget |
| `owner`     | `owner@example.com`  | a human email for "who to ask" when a cost spike appears |

Additional optional tags can be layered on (`feature`, `cost_center`,
`ticket`) but the four above are the non-negotiable minimum. Every
query in `docs/cost-attribution/queries/` groups by `workload` by
default and optionally pivots by `team` or `env`.

## Principle: cluster tags propagate to billing automatically

Databricks copies cluster and warehouse tags into
`system.billing.usage.custom_tags` once per billing period for the
resources they were attached to. The tag-to-usage link is automatic.
The only manual step is ensuring the tag was present at create time
(or edit time, for already-running resources). Untagged resources
show up with a `NULL` or empty `custom_tags` map and get lumped into
an "unattributed" bucket in every dashboard.

The same propagation works for serving endpoints. Jobs also carry
their cluster tags through the run cost records.

## Principle: enforcement via compute policies, not via trust

Tagging compliance that depends on humans remembering to add tags
decays fast. The recommended enforcement pattern:

1. **Create a "tagged-workload" compute policy** for each team that
   owns clusters / warehouses. The policy pre-fills the `workload`,
   `team`, `env`, and `owner` tags and marks the `workload` tag
   `fixed` so it cannot be removed. See the Databricks compute
   policy docs for the JSON shape. The relevant policy fields are
   `custom_tags.workload`, `custom_tags.team`, and siblings.
2. **Restrict cluster creation** for the team to that policy via
   workspace-level permissions. Non-policy cluster creation is
   still possible for admins but becomes the exception.
3. **For SQL warehouses**, the workspace admin sets the tags on
   the warehouse directly at creation time (see
   `warehouse_setup.sql`). Warehouses cannot be constrained by
   compute policies the same way clusters can, so the enforcement
   here is "create the warehouse once with the right tags, don't
   let anyone else create untagged ones on the same team."
4. **For serving endpoints**, tags go on the endpoint's
   `tags` field at creation time. There is no policy-based
   enforcement today. Relying on the team's launch checklist is
   the current answer.

## Principle: a dedicated SQL warehouse per workload

For any workload where cost attribution is important, create a
**dedicated SQL warehouse** rather than sharing a team warehouse.
Reasons:

1. **Isolation**. All queries from the workload hit one warehouse
   whose tags are stable, so every billing row is correctly
   attributed without having to tag individual queries.
2. **Cost ceiling**. You can set a distinct auto-stop and max
   cluster count per workload, preventing runaway spend from one
   workload affecting the rest.
3. **Usage-based rate limiting**. If the LLM side of the workload
   (e.g. a planner loop) can fire 10 SQL queries per user turn,
   isolating them on their own warehouse lets you size the
   warehouse to absorb that burst without starving interactive
   users.
4. **Serverless first**. Use a serverless SQL warehouse, not a
   classic one. Serverless warehouses have sub-second start time,
   so the auto-stop window can be aggressive (1-5 minutes)
   without hurting UX. Classic warehouses take minutes to start
   and encourage longer idle windows, which is pure waste.

See `warehouse_setup.sql` for the create template.

## Budget alerts

Once the dashboards are wired, set three budget alerts per team in
the Databricks account console:

| Alert            | Threshold       | Action |
|------------------|-----------------|--------|
| **warning**      | 50% of monthly  | email team owner |
| **urgent**       | 80% of monthly  | email team owner + platform lead |
| **kill-switch**  | 100% of monthly | email everyone + trigger review meeting |

Budgets are account-level, not workspace-level, so they need an
account admin to wire them. This is a 10-minute click-through in the
Databricks account console, not a code change.

## Migration path for existing unshared resources

If the team is already running workloads on shared / untagged
compute, the migration plan is:

1. **Tag the existing clusters / warehouses in place.** You can
   edit tags on a running warehouse via the UI or API. This
   starts producing tagged billing rows immediately, which is
   the fastest way to show attribution in a dashboard.
2. **Stand up the dedicated per-workload warehouse.** Give it the
   tags from day one. Run both old and new in parallel for 1-2
   weeks to validate the new attribution is correct.
3. **Cut over**. Point the application at the new warehouse.
   Archive the old one.
4. **Backfill dashboards.** Most queries in
   `docs/cost-attribution/queries/` filter on tag values at query
   time, so once the historical rows have tags, the dashboards
   start showing the full picture automatically. No re-run
   needed.

## Known gaps in this draft

- **No cost-per-agent-turn view.** The agent framework emits
  invocations, not turns, so the existing `serving_endpoint_cost.sql`
  query gives spend per invocation, not per user turn. Adding a
  user-turn view requires joining the inference table (if enabled)
  against the serving billing rows on `request_id`. Follow-up.
- **No FinOps team coordination.** If the customer has a central
  FinOps function, the policy here needs to harmonize with whatever
  existing tagging policy they already use for non-Databricks
  workloads. That's an org conversation, not a code one.
- **No Claude (Anthropic direct) cost**. Direct Anthropic API cost
  is tracked separately and out of scope for the Databricks-side
  story. We explicitly do not pull it in.
