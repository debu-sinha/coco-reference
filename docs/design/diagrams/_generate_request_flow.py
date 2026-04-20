"""Generate the README request-flow diagram as an Excalidraw JSON file.

Run: `python docs/design/diagrams/_generate_request_flow.py`
Output: `docs/design/diagrams/request-flow.excalidraw`

The file opens in excalidraw.com for visual polish. Regenerate by
editing this script and re-running — hand-editing the JSON is
fragile.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path


def _base(el_type: str) -> dict:
    """Fields every Excalidraw element needs."""
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


def text(x: int, y: int, body: str, size: int = 18, width: int = 240) -> dict:
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
            "fontFamily": 1,  # Virgil (hand-drawn)
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": size - 2,
            "containerId": None,
            "originalText": body,
            "lineHeight": 1.25,
        }
    )
    return el


def arrow(start: tuple[int, int], end: tuple[int, int], label: str = "") -> list[dict]:
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
            "startArrowhead": None,
            "endArrowhead": "arrow",
        }
    )
    out = [el]
    if label:
        lx = (sx + ex) // 2 - 80
        ly = (sy + ey) // 2 - 10
        out.append(text(lx, ly, label, size=14, width=160))
    return out


def label_pair(rect_el: dict, body: str) -> dict:
    """Text centered inside a rectangle."""
    return text(
        rect_el["x"] + 10,
        rect_el["y"] + rect_el["height"] // 2 - 12,
        body,
        size=18,
        width=rect_el["width"] - 20,
    )


def build_elements() -> list[dict]:
    els: list[dict] = []

    # Column 1 — main vertical flow
    col1_x, col1_w = 220, 280
    user = rect(col1_x, 60, col1_w, 70, fill="#ffd8a8")
    user_label = label_pair(user, "User question")
    app = rect(col1_x, 200, col1_w, 80, fill="#d0bfff")
    app_label = label_pair(app, "Databricks App\nFastAPI + HTMX + SSE")
    lake = rect(col1_x, 350, col1_w, 80, fill="#a5d8ff")
    lake_label = label_pair(lake, "Lakebase\nthreads / messages / feedback")
    agent = rect(col1_x, 500, col1_w, 90, fill="#b2f2bb")
    agent_label = label_pair(agent, "Agent Serving\nDSPy ReAct on Mosaic AI")

    els.extend([user, user_label, app, app_label, lake, lake_label, agent, agent_label])

    # Column 1 down-arrows
    mid = col1_x + col1_w // 2
    els.extend(arrow((mid, 130), (mid, 195)))
    els.extend(arrow((mid, 280), (mid, 345)))
    els.extend(arrow((mid, 430), (mid, 495)))

    # Column 2 — tool fanout
    col2_x, col2_w = 640, 300
    tools = [
        ("Claude Sonnet 4.6 (FMAPI)", "plan + synthesize via AI Gateway", "#ffc9c9"),
        ("SQL Warehouse", "execute cohort queries", "#ffd8a8"),
        ("Vector Search", "clinical knowledge RAG", "#a5d8ff"),
        ("MLflow Prompt Registry", "versioned prompts @production", "#d0bfff"),
        ("MLflow Traces + Experiments", "every tool call + user attribution", "#b2f2bb"),
    ]
    base_y = 260
    step = 120
    for i, (name, desc, fill) in enumerate(tools):
        ty = base_y + i * step
        r = rect(col2_x, ty, col2_w, 70, fill=fill)
        els.append(r)
        els.append(label_pair(r, f"{name}\n{desc}"))
        els.extend(
            arrow(
                (col1_x + col1_w, agent["y"] + agent["height"] // 2),
                (col2_x, ty + 35),
            )
        )

    # Title
    els.append(
        text(
            200,
            5,
            "CoCo v2 — Request flow",
            size=26,
            width=600,
        )
    )

    return els


def main() -> None:
    data = {
        "type": "excalidraw",
        "version": 2,
        "source": "coco-reference / docs/design/diagrams/_generate_request_flow.py",
        "elements": build_elements(),
        "appState": {
            "gridSize": None,
            "viewBackgroundColor": "#ffffff",
        },
        "files": {},
    }
    out = Path(__file__).with_name("request-flow.excalidraw")
    out.write_text(json.dumps(data, indent=2))
    print(f"wrote {out} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
