"""Pre-flight workspace permission check for CoCo deployment.

Run this BEFORE `databricks bundle deploy` to verify your workspace
has all the features and permissions needed for the setup job. It
checks every resource the setup notebook will try to create and
reports pass/fail/warn for each one.

Usage:
    python scripts/preflight_check.py -p PROFILE --warehouse-id WH_ID

    Optional:
        --catalog CATALOG    Catalog name (default: coco_demo)
        --unique-id ID       Your namespace id (default: dev)

Example:
    python scripts/preflight_check.py -p YOUR_PROFILE --warehouse-id YOUR_WAREHOUSE_ID
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="CoCo pre-flight workspace check")
    parser.add_argument("-p", "--profile", required=True, help="Databricks CLI profile name")
    parser.add_argument("--warehouse-id", required=True, help="Serverless SQL warehouse ID")
    parser.add_argument("--catalog", default="coco_demo", help="UC catalog name")
    parser.add_argument("--unique-id", default="dev", help="Namespace ID (your initials)")
    args = parser.parse_args()

    import os

    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    passed = 0
    failed = 0
    warned = 0

    def ok(msg: str) -> None:
        nonlocal passed
        passed += 1
        print(f"  PASS  {msg}")

    def fail(msg: str) -> None:
        nonlocal failed
        failed += 1
        print(f"  FAIL  {msg}")

    def warn(msg: str) -> None:
        nonlocal warned
        warned += 1
        print(f"  WARN  {msg}")

    print("\nCoCo Pre-flight Check")
    print(f"Workspace: {w.config.host}")
    print(f"Profile:   {args.profile}")
    print(f"Catalog:   {args.catalog}")
    print(f"Unique ID: {args.unique_id}")
    print()

    # 1. Auth
    print("1. Authentication")
    try:
        me = w.current_user.me()
        ok(f"Authenticated as {me.display_name} ({me.user_name})")
    except Exception as e:
        fail(f"Authentication failed: {e}")
        print("\nCannot proceed without authentication. Fix your CLI profile.")
        return 1

    # 2. SQL Warehouse
    print("\n2. SQL Warehouse")
    try:
        wh = w.warehouses.get(id=args.warehouse_id)
        ok(
            f"Warehouse found: {wh.name} (serverless={wh.enable_serverless_compute}, state={wh.state})"
        )
        if not wh.enable_serverless_compute:
            warn("Warehouse is not serverless. Serverless is recommended for cost + speed.")
    except Exception as e:
        fail(f"Cannot access warehouse {args.warehouse_id}: {e}")

    # 3. FMAPI / Claude endpoint (existence + CAN_QUERY smoke test)
    print("\n3. Foundation Model API (Claude)")
    claude_found = None
    try:
        endpoints = list(w.serving_endpoints.list())
        for ep in endpoints:
            if "claude" in (ep.name or "").lower() and "sonnet" in (ep.name or "").lower():
                ready = ep.state.ready if ep.state else "?"
                ok(f"Found {ep.name} (ready={ready})")
                claude_found = ep.name
                break
        if not claude_found:
            for ep in endpoints:
                if "claude" in (ep.name or "").lower():
                    ok(f"Found {ep.name} (not Sonnet but usable)")
                    claude_found = ep.name
                    break
        if not claude_found:
            fail(
                "No Claude FMAPI endpoint found. The agent needs a "
                "databricks-claude-sonnet-* endpoint (4-5, 4-6, etc)."
            )
    except Exception as e:
        fail(f"Cannot list serving endpoints: {e}")

    # 3a. CAN_QUERY smoke test - one token, prove invocation actually works
    if claude_found:
        # Hit the invocations endpoint directly via an authenticated POST.
        # The SDK's serving_endpoints.query() has version-dependent schema
        # handling (some versions expect ChatMessage objects, others dicts)
        # which makes smoke-testing brittle across runtimes. A raw POST with
        # the workspace's auth headers bypasses all of that.
        import json as _json

        try:
            host = w.config.host.rstrip("/")
            hdrs = w.config.authenticate()
            import urllib.request

            req = urllib.request.Request(
                f"{host}/serving-endpoints/{claude_found}/invocations",
                method="POST",
                data=_json.dumps(
                    {
                        "messages": [{"role": "user", "content": "ok"}],
                        "max_tokens": 1,
                    }
                ).encode(),
                headers={
                    "Authorization": hdrs["Authorization"],
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                body = _json.loads(r.read().decode())
            if body.get("choices") or body.get("output") or body.get("predictions"):
                ok(f"CAN_QUERY on {claude_found} (smoke test succeeded)")
            else:
                warn(f"Invocation of {claude_found} returned unexpected shape: {list(body.keys())}")
        except Exception as e:
            fail(
                f"CAN_QUERY on {claude_found} failed. The setup job will crash "
                f"at agent deploy. Error: {type(e).__name__}: {str(e)[:200]}"
            )

    # 3b. config.yaml LLM endpoint matches what is deployed
    try:
        import os as _os

        repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        cfg_path = _os.path.join(repo_root, "config", "default.yaml")
        if _os.path.exists(cfg_path):
            import yaml as _yaml

            with open(cfg_path) as _f:
                cfg = _yaml.safe_load(_f)
            declared = cfg.get("llm", {}).get("endpoint", "")
            if declared and claude_found and declared != claude_found:
                # Substring match is fine (e.g. declared=claude-sonnet-4-5,
                # deployed=databricks-claude-sonnet-4-5).
                if declared not in claude_found and claude_found not in declared:
                    warn(
                        f"config/default.yaml declares llm.endpoint={declared!r} "
                        f"but the workspace ships {claude_found!r}. The agent "
                        f"will fail to call the LLM at runtime. Edit the yaml "
                        f"before running the setup job."
                    )
                else:
                    ok("config/default.yaml llm.endpoint matches deployed endpoint")
            elif declared == claude_found:
                ok("config/default.yaml llm.endpoint matches deployed endpoint")
    except Exception as e:
        warn(f"Could not cross-check config.yaml against deployed endpoint: {e}")

    # 4. Unity Catalog
    print("\n4. Unity Catalog")
    catalog_exists = False
    try:
        catalogs = [c.name for c in w.catalogs.list()]
        if args.catalog in catalogs:
            ok(f"Catalog '{args.catalog}' exists")
            catalog_exists = True
        else:
            avail = ", ".join(c for c in catalogs if c not in ("system", "samples"))
            fail(
                f"Catalog '{args.catalog}' does not exist. The setup job's CREATE CATALOG "
                f"will fail on any workspace with Default Storage enabled (most new "
                f"workspaces). Either pre-create the catalog in the UI, or re-run the "
                f"bundle deploy with --var catalog=<existing-name>.\n"
                f"         Available catalogs: {avail}"
            )
    except Exception as e:
        fail(f"Cannot list catalogs: {e}")

    if catalog_exists:
        schema_name = f"cohort_builder_{args.unique_id}"
        try:
            schemas = [s.name for s in w.schemas.list(catalog_name=args.catalog)]
            if schema_name in schemas:
                ok(f"Schema '{args.catalog}.{schema_name}' already exists (will reuse)")
            else:
                ok(f"Schema '{schema_name}' does not exist yet (will be created by setup)")
        except Exception as e:
            warn(f"Cannot list schemas in {args.catalog}: {e}")

        # CREATE SCHEMA permission probe - listing a catalog does not imply
        # CREATE SCHEMA. This is the #1 silent failure for restricted users,
        # so try to create + drop a probe schema instead of trusting grants.
        import uuid as _uuid

        probe_name = f"_coco_preflight_probe_{_uuid.uuid4().hex[:8]}"
        probe_fqn = f"{args.catalog}.{probe_name}"
        try:
            w.schemas.create(name=probe_name, catalog_name=args.catalog)
            try:
                w.schemas.delete(full_name=probe_fqn)
            except Exception:
                pass
            ok(f"CREATE SCHEMA permission on '{args.catalog}' (probe succeeded)")
        except Exception as e:
            fail(
                f"CREATE SCHEMA on '{args.catalog}' FAILED. You can list the "
                f"catalog but cannot create schemas inside it. Setup job will "
                f"crash at Step 2. Ask admin: "
                f"'GRANT USE CATALOG, CREATE SCHEMA ON CATALOG {args.catalog} "
                f"TO `<your-email>`'. Error: {type(e).__name__}: {str(e)[:150]}"
            )

    # 5. Lakebase
    print("\n5. Lakebase (Managed Postgres)")
    try:
        instances = list(w.database.list_database_instances())
        ok(f"Lakebase API accessible ({len(instances)} instances found)")
        if instances:
            names = [i.name for i in instances[:5]]
            print(f"         Existing instances: {', '.join(names)}")
    except Exception as e:
        if "not found" in str(e).lower() or "404" in str(e):
            warn(
                "Lakebase API not available on this workspace. Session persistence will be skipped."
            )
        else:
            warn(f"Lakebase API error (may still work): {e}")

    # 6. Vector Search
    print("\n6. Vector Search")
    try:
        vs_eps = list(w.vector_search_endpoints.list_endpoints())
        ok(f"Vector Search API accessible ({len(vs_eps)} endpoints found)")
    except Exception as e:
        warn(f"Vector Search API error: {e}")

    # 7. Databricks Apps
    print("\n7. Databricks Apps")
    try:
        apps = list(w.apps.list())
        ok(f"Apps API accessible ({len(apps)} apps found)")
    except Exception as e:
        warn(f"Apps API error: {e}")

    # 8. MLflow (config + Prompt Registry preview flag probe)
    print("\n8. MLflow")
    try:
        import mlflow

        mlflow.set_tracking_uri("databricks")
        mlflow.set_registry_uri("databricks-uc")
        ok("MLflow tracking + registry configured for Databricks")
    except Exception as e:
        warn(f"MLflow setup issue: {e}")

    # 8a. MLflow Prompt Registry preview flag probe. The README says this
    # preview flag is required; listing models does not prove the flag is
    # on. Only register_prompt call does. Do a register + delete on a
    # throwaway 3-part UC name inside the user's catalog + namespaced schema.
    if catalog_exists:
        try:
            import uuid as _uuid

            import mlflow.genai as _mg

            probe_schema = f"cohort_builder_{args.unique_id}"
            # Need the schema to actually exist. If it doesn't, create a tiny one
            # just for the probe (cheaper than the CREATE SCHEMA probe above).
            probe_schemas = [s.name for s in w.schemas.list(catalog_name=args.catalog)]
            ephemeral_schema = False
            if probe_schema not in probe_schemas:
                # Use an ephemeral schema purely for the probe. Harmless because
                # the setup job creates the real one later.
                probe_schema = f"_coco_preflight_schema_{_uuid.uuid4().hex[:6]}"
                try:
                    w.schemas.create(name=probe_schema, catalog_name=args.catalog)
                    ephemeral_schema = True
                except Exception:
                    probe_schema = None  # type: ignore[assignment]

            if probe_schema:
                probe_prompt = (
                    f"{args.catalog}.{probe_schema}._coco_preflight_{_uuid.uuid4().hex[:8]}"
                )
                try:
                    _mg.register_prompt(name=probe_prompt, template="preflight probe")
                    ok("MLflow Prompt Registry preview flag is enabled")
                    # mlflow.genai has no delete_prompt helper. Prompts are
                    # registered as UC registered models under the hood, so
                    # use MlflowClient.delete_registered_model to clean up.
                    try:
                        import mlflow as _mlflow

                        _mlflow.MlflowClient().delete_registered_model(name=probe_prompt)
                    except Exception:
                        pass  # one leftover probe row is harmless
                except Exception as e:
                    fail(
                        f"MLflow Prompt Registry probe FAILED. The 'MLflow "
                        f"Prompt Registry' preview flag is likely not enabled, or "
                        f"you lack UC write permission. Enable it from your username "
                        f"menu -> Previews. Error: {type(e).__name__}: {str(e)[:150]}"
                    )
                if ephemeral_schema:
                    try:
                        w.schemas.delete(full_name=f"{args.catalog}.{probe_schema}")
                    except Exception:
                        pass
        except ImportError:
            warn(
                "mlflow.genai not importable from the local Python environment. "
                "The notebook environment installs it fresh, so this is usually "
                "fine, but the preflight could not verify the preview flag."
            )
        except Exception as e:
            warn(f"Prompt Registry probe skipped: {type(e).__name__}: {str(e)[:150]}")

    # 9. Model Serving (can create endpoints)
    print("\n9. Model Serving (endpoint creation)")
    endpoint_name = f"coco-agent-{args.unique_id}"
    try:
        existing = None
        for ep in w.serving_endpoints.list():
            if ep.name == endpoint_name:
                existing = ep
                break
        if existing:
            ok(f"Endpoint '{endpoint_name}' already exists (will update)")
        else:
            ok(f"Endpoint '{endpoint_name}' does not exist (will be created by setup)")
    except Exception as e:
        warn(f"Cannot check serving endpoints: {e}")

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {warned} warnings")
    print(f"{'=' * 50}")

    if failed > 0:
        print("\nFIX the FAIL items above before running the setup job.")
        print("See docs/PERMISSIONS.md for how to request each permission.")
        return 1
    elif warned > 0:
        print("\nWARN items may cause issues. The setup job will try to handle them")
        print("gracefully, but check docs/PERMISSIONS.md if anything fails.")
        return 0
    else:
        print("\nAll checks passed. You're ready to deploy:")
        print(f"  databricks bundle deploy -t demo -p {args.profile} \\")
        print(f"    --var unique_id={args.unique_id} \\")
        print(f"    --var warehouse_id={args.warehouse_id} \\")
        print(f"    --var catalog={args.catalog}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
