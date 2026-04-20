"""Excalidraw source for the apps + Mosaic AI reference architecture.

Run: `python docs/design/diagrams/_generate_apps_mosaic_ai_reference.py`
Output: `docs/design/diagrams/apps-mosaic-ai-reference.excalidraw`

Shows the runtime path for one user question: browser -> Databricks App
(FastAPI, X-Forwarded-Email auth) -> CocoAgent (DSPy ReAct) -> three
parallel tool surfaces (Mosaic AI Gateway, UC SQL, Vector Search), with
Lakebase for sessions and MLflow for traces.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path


def _base(el_type: str) -> dict:
    return {
        "id": f"el-{random.randint(10**9, 10**10)}",
        "type": el_type,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "seed": random.randint(1, 2**31),
        "version": 1,
        "versionNonce": random.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": None,
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
    }


def rect(x: int, y: int, w: int, h: int, fill: str = "#b2f2bb") -> dict:
    el = _base("rectangle")
    el.update(
        {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "backgroundColor": fill,
            "fillStyle": "hachure",
            "roundness": {"type": 3},
        }
    )
    return el


def text(x: int, y: int, body: str, size: int = 16, width: int = 240) -> dict:
    el = _base("text")
    lines = body.count("\n") + 1
    el.update(
        {
            "x": x,
            "y": y,
            "width": width,
            "height": size * lines + 6,
            "text": body,
            "fontSize": size,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": size - 2,
            "containerId": None,
            "originalText": body,
            "lineHeight": 1.25,
        }
    )
    return el


def label(r: dict, body: str, size: int = 16) -> dict:
    return text(
        r["x"] + 8,
        r["y"] + r["height"] // 2 - 14,
        body,
        size=size,
        width=r["width"] - 16,
    )


def arrow(
    start: tuple[int, int],
    end: tuple[int, int],
    dashed: bool = False,
    two_way: bool = False,
) -> dict:
    el = _base("arrow")
    sx, sy = start
    ex, ey = end
    el.update(
        {
            "x": sx,
            "y": sy,
            "width": abs(ex - sx) or 1,
            "height": abs(ey - sy) or 1,
            "points": [[0, 0], [ex - sx, ey - sy]],
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": "arrow" if two_way else None,
            "endArrowhead": "arrow",
            "strokeStyle": "dashed" if dashed else "solid",
        }
    )
    return el


def build_elements() -> list[dict]:
    els: list[dict] = []

    # Title + caption
    els.append(text(280, 10, "CoCo — Apps + Mosaic AI reference", size=22, width=720))
    els.append(
        text(
            280,
            40,
            "one request: browser -> App -> agent -> tool surfaces",
            size=14,
            width=720,
        )
    )

    # Row 1: user browser (center)
    user = rect(460, 90, 240, 60, fill="#ffd8a8")
    els.append(user)
    els.append(label(user, "User browser"))

    # Row 2: Databricks App (center) + Lakebase (right)
    app = rect(380, 190, 400, 80, fill="#a5d8ff")
    els.append(app)
    els.append(label(app, "Databricks App (FastAPI)\nX-Forwarded-Email auth"))

    lakebase = rect(830, 190, 240, 80, fill="#ffe066")
    els.append(lakebase)
    els.append(label(lakebase, "Lakebase Postgres\nthreads / messages /\nruns / feedback", size=12))

    # User -> App
    els.append(arrow((580, 150), (580, 188)))
    # App <-> Lakebase (two-way: session read/write)
    els.append(arrow((780, 230), (828, 230), two_way=True))

    # Row 3: CocoAgent (center)
    agent = rect(380, 320, 400, 80, fill="#b2f2bb")
    els.append(agent)
    els.append(label(agent, "CocoAgent\nDSPy ReAct loop (max_turns=10)"))

    # App -> Agent
    els.append(arrow((580, 270), (580, 318)))

    # MLflow experiment (right of agent)
    mlflow = rect(830, 320, 240, 80, fill="#e599f7")
    els.append(mlflow)
    els.append(label(mlflow, "MLflow experiment\nspans + traces"))

    # Agent -> MLflow (dashed = passive logging)
    els.append(arrow((780, 360), (828, 360), dashed=True))

    # Row 4: three tool surfaces
    gateway = rect(60, 470, 280, 90, fill="#ffc9c9")
    els.append(gateway)
    els.append(
        label(
            gateway,
            "Mosaic AI Gateway\nroute: coco-llm\n(Claude Sonnet 4.5)",
            size=12,
        )
    )

    uc_sql = rect(400, 470, 360, 90, fill="#ffc9c9")
    els.append(uc_sql)
    els.append(
        label(
            uc_sql,
            "Unity Catalog SQL\nStatement Execution API\n+ serverless warehouse",
            size=12,
        )
    )

    vs_index = rect(820, 470, 280, 90, fill="#ffc9c9")
    els.append(vs_index)
    els.append(
        label(
            vs_index,
            "Databricks Vector Search\ncoco_knowledge_idx\n(BM25 + BGE hybrid)",
            size=12,
        )
    )

    # Agent -> each tool surface
    els.append(arrow((460, 400), (200, 468)))  # -> gateway
    els.append(arrow((580, 400), (580, 468)))  # -> uc sql
    els.append(arrow((700, 400), (960, 468)))  # -> vs index

    # Tool annotations beneath each
    els.append(text(60, 570, "every LLM call (planner + synthesizer)", size=11, width=280))
    els.append(text(400, 570, "guardrails: read-only + schema allowlist", size=11, width=360))
    els.append(text(820, 570, "clinical-knowledge RAG tool", size=11, width=280))

    return els


def main() -> None:
    data = {
        "type": "excalidraw",
        "version": 2,
        "source": "coco-reference / docs/design/diagrams/_generate_apps_mosaic_ai_reference.py",
        "elements": build_elements(),
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    out = Path(__file__).with_name("apps-mosaic-ai-reference.excalidraw")
    out.write_text(json.dumps(data, indent=2))
    print(f"wrote {out} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
