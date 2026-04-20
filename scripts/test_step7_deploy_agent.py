"""Standalone test for the Step 7 agent-deploy logic.

Runs `coco.agent.deploy.deploy_agent()` directly from a local Python
process using the developer's Databricks CLI auth. Iterates in seconds
instead of requiring a fresh jobs-cluster run of the full setup
notebook.

Usage:
    DATABRICKS_CONFIG_PROFILE=<your-profile> \\
    python scripts/test_step7_deploy_agent.py

Prerequisites (install locally):
    pip install 'mlflow>=3.1' 'databricks-agents>=1.1' 'dspy>=2.5' \\
        'databricks-sdk>=0.30' 'databricks-vectorsearch>=0.40' \\
        'httpx>=0.27' 'pydantic>=2.5' 'pyyaml>=6.0' 'sqlparse>=0.5'
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SRC_DIR = REPO_ROOT / "src"

sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("COCO_CONFIG_PATH", str(REPO_ROOT / "config" / "default.yaml"))

# DATABRICKS_HOST for GatewayClient and MLflow auth.
if "DATABRICKS_HOST" not in os.environ:
    # Pull from the active profile if we can.
    try:
        from databricks.sdk.core import Config

        cfg = Config()
        os.environ["DATABRICKS_HOST"] = cfg.host or ""
    except Exception:
        pass

# Pick up the local CLI warehouse id override for config resolution,
# since the workshop notebook passes it as a widget.
os.environ.setdefault("COCO_WAREHOUSE_ID", "")
if not os.environ.get("COCO_WAREHOUSE_ID"):
    print(
        "ERROR: COCO_WAREHOUSE_ID is required. Set it to a serverless warehouse id (hex string).",
        file=sys.stderr,
    )
    sys.exit(2)
os.environ.setdefault("COCO_AGENT_ENDPOINT_URL", "")

from coco.agent.deploy import deploy_agent  # noqa: E402


def main() -> int:
    print(f"Repo root: {REPO_ROOT}")
    print(f"Config path: {os.environ['COCO_CONFIG_PATH']}")
    print(f"Databricks host: {os.environ.get('DATABRICKS_HOST', '<unset>')}")
    print()
    deploy_agent()
    print("\nDeploy complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
