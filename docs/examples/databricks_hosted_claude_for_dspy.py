"""Call databricks-claude-sonnet-4-5 from outside Databricks.

Three working patterns, in order of increasing abstraction:

    1. Raw httpx  - prove auth + URL work before bringing in frameworks
    2. OpenAI SDK - if you already have OpenAI code, this is a one-line swap
    3. DSPy       - if you're running DSPy modules today, this is the swap

All three use the same auth model: a Databricks Personal Access Token
with CAN_QUERY on the target serving endpoint. You do NOT need any
special OAuth scope on the PAT; the CAN_QUERY permission on the
endpoint is what the platform checks.

Create the PAT with:

    1. Workspace UI: User menu -> User Settings -> Developer ->
       Access tokens -> Generate new token.
    2. Or CLI: `databricks tokens create --lifetime-seconds 2592000
       --comment coco-dspy`
    3. Or Service principal PAT via the SDK: `WorkspaceClient().
       tokens.create(...)`. Do this for production; user PATs are
       fine for a development swap like this one.

Then grant your principal CAN_QUERY on the endpoint:

    1. Workspace UI: Machine Learning -> Serving -> select
       `databricks-claude-sonnet-4-5` -> Permissions -> Can Query ->
       add your user or SP.
    2. Or CLI: `databricks serving-endpoints update-permissions
       databricks-claude-sonnet-4-5 --json '{"access_control_list":
       [{"user_name": "you@example.com",
       "permission_level": "CAN_QUERY"}]}'`

That's the entire scope story. There is no `serving.*` scope on the
PAT itself; the PAT is a bearer token and the endpoint ACL is what
gates access.

Env vars this script reads:

    DATABRICKS_HOST   - e.g. "https://your-workspace.cloud.databricks.com"
                        (with or without the https:// prefix)
    DATABRICKS_TOKEN  - the PAT you just minted
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# 0. Env + auth
# ---------------------------------------------------------------------------

HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
if not HOST.startswith("http"):
    HOST = f"https://{HOST}"
TOKEN = os.environ["DATABRICKS_TOKEN"]
ENDPOINT_NAME = os.environ.get("DATABRICKS_SERVING_ENDPOINT", "databricks-claude-sonnet-4-5")

SAMPLE_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are a helpful healthcare data analyst. Be concise and "
            "cite specific ICD-10 or RxNorm codes when relevant."
        ),
    },
    {
        "role": "user",
        "content": (
            "What are the ICD-10 codes for Type 2 diabetes mellitus? "
            "Respond with a short bulleted list."
        ),
    },
]


# ---------------------------------------------------------------------------
# 1. Raw httpx - no framework, just the OpenAI-compatible chat shape
# ---------------------------------------------------------------------------


def call_with_httpx() -> str:
    """Direct POST to /serving-endpoints/<name>/invocations.

    Use this pattern when you want to rule out framework issues and
    confirm the PAT, endpoint name, and ACL are correct.
    """
    import httpx

    url = f"{HOST}/serving-endpoints/{ENDPOINT_NAME}/invocations"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": SAMPLE_MESSAGES,
        "max_tokens": 512,
        "temperature": 0.0,
    }

    r = httpx.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# 2. OpenAI SDK - if you already use the `openai` Python package
# ---------------------------------------------------------------------------


def call_with_openai_sdk() -> str:
    """Reuse the OpenAI SDK with the Databricks serving base URL.

    Databricks Model Serving exposes an OpenAI-compatible chat
    completions shape at `/serving-endpoints/<name>/invocations`, so
    the OpenAI Python client works with:
        - api_key   = your Databricks PAT
        - base_url  = https://<workspace>/serving-endpoints
        - model     = endpoint name (e.g. "databricks-claude-sonnet-4-5")

    Swap your existing `OpenAI(api_key=..., base_url=...)` init for
    this one and the rest of your code stays identical.
    """
    from openai import OpenAI

    client = OpenAI(
        api_key=TOKEN,
        base_url=f"{HOST}/serving-endpoints",
    )
    resp = client.chat.completions.create(
        model=ENDPOINT_NAME,
        messages=SAMPLE_MESSAGES,
        max_tokens=512,
        temperature=0.0,
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 3. DSPy - the pattern for swapping an existing `dspy.LM` config
# ---------------------------------------------------------------------------


def call_with_dspy() -> str:
    """Point DSPy's LM at Databricks-hosted Claude.

    DSPy 2.5+ uses LiteLLM under the hood, and LiteLLM has first-class
    Databricks serving support. The model string is
    `databricks/<endpoint-name>`, the `api_base` is the workspace host
    plus `/serving-endpoints`, and the `api_key` is your PAT.

    Replace your current LM config (OpenAI, Anthropic, etc.) with:

        import dspy
        lm = dspy.LM(
            "databricks/databricks-claude-sonnet-4-5",
            api_base=f"{HOST}/serving-endpoints",
            api_key=TOKEN,
            max_tokens=2000,
            temperature=0.0,
        )
        dspy.configure(lm=lm)

    All your existing `dspy.Predict`, `dspy.ChainOfThought`, and
    `dspy.ReAct` modules will route through Databricks without any
    other code changes.
    """
    import dspy

    lm = dspy.LM(
        "databricks/databricks-claude-sonnet-4-5",
        api_base=f"{HOST}/serving-endpoints",
        api_key=TOKEN,
        max_tokens=512,
        temperature=0.0,
    )
    dspy.configure(lm=lm)

    # Minimal DSPy signature + module for the smoke test.
    class ClinicalCodeLookup(dspy.Signature):
        """Return clinical codes for a given condition."""

        condition: str = dspy.InputField()
        codes: str = dspy.OutputField(desc="Short bulleted list of ICD-10 codes with descriptions.")

    program = dspy.Predict(ClinicalCodeLookup)
    result = program(condition="Type 2 diabetes mellitus")
    return result.codes


# ---------------------------------------------------------------------------
# Smoke-test runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "httpx"
    print(f"[host] {HOST}")
    print(f"[endpoint] {ENDPOINT_NAME}")
    print(f"[mode] {which}")
    print()

    if which == "httpx":
        text = call_with_httpx()
    elif which == "openai":
        text = call_with_openai_sdk()
    elif which == "dspy":
        text = call_with_dspy()
    else:
        print(f"unknown mode: {which}. use one of: httpx | openai | dspy")
        sys.exit(2)

    print(text)
