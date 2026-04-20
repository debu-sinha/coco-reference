"""Excalidraw source for the MLflow trace structure.

Run: `python docs/design/diagrams/_generate_mlflow_trace_structure.py`
Output: `docs/design/diagrams/mlflow-trace-structure.excalidraw`

Shows one agent invocation as a span tree. `agent_turn` is the root.
Under it sit the per-iteration spans: `plan_action` (every loop) and
`tool_<name>` for whichever tool ran, then a terminal `synthesize_response`.
LLM calls under every span are auto-traced by mlflow.dspy.autolog().
The trace is what the 4 scorers in notebooks/02_evaluate.py consume,
and what optimize_prompts pulls thumbs-up feedback from.
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


def arrow(start: tuple[int, int], end: tuple[int, int], dashed: bool = False) -> dict:
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
            "strokeStyle": "dashed" if dashed else "solid",
        }
    )
    return el


def build_elements() -> list[dict]:
    els: list[dict] = []

    # Title + caption
    els.append(text(240, 10, "CoCo — MLflow trace structure", size=22, width=720))
    els.append(
        text(
            240,
            40,
            "one agent invocation as a span tree (mlflow.dspy.autolog adds LM sub-spans)",
            size=13,
            width=720,
        )
    )

    # Root: agent_turn (wide bar at top)
    root = rect(100, 100, 1080, 60, fill="#ffd8a8")
    els.append(root)
    els.append(label(root, "agent_turn  (root span, one per user message)"))

    # Level 1 children — 6 boxes side-by-side under the root
    children_y = 220
    children_h = 70
    child_w = 170
    gap = 10
    x0 = 100
    labels = [
        ("plan_action", "#a5d8ff"),
        ("tool_clinical_codes", "#b2f2bb"),
        ("tool_sql_generator", "#b2f2bb"),
        ("tool_sql_executor", "#b2f2bb"),
        ("tool_knowledge_rag", "#b2f2bb"),
        ("synthesize_response", "#ffc9c9"),
    ]
    children_rects: list[dict] = []
    for i, (name, fill) in enumerate(labels):
        x = x0 + i * (child_w + gap)
        r = rect(x, children_y, child_w, children_h, fill=fill)
        els.append(r)
        els.append(label(r, name, size=13))
        children_rects.append(r)
        # arrow from root down to each child
        root_bottom_x = x + child_w // 2
        els.append(arrow((root_bottom_x, 160), (root_bottom_x, children_y - 2)))

    # Level 2 — LM subspan under each child (one representative row)
    lm_y = 320
    lm_h = 50
    for r in children_rects:
        lm = rect(r["x"] + 20, lm_y, r["width"] - 40, lm_h, fill="#e599f7")
        els.append(lm)
        els.append(label(lm, "LM call", size=12))
        cx = r["x"] + r["width"] // 2
        els.append(arrow((cx, children_y + children_h), (cx, lm_y - 2)))

    # Annotation under LM row
    els.append(
        text(
            100,
            390,
            "mlflow.dspy.autolog() attaches one LM sub-span per DSPy module call",
            size=12,
            width=1080,
        )
    )

    # Right-side consumers: scorers + optimizer
    scorers = rect(100, 450, 500, 80, fill="#d0bfff")
    els.append(scorers)
    els.append(
        label(
            scorers,
            "4 scorers in notebooks/02_evaluate.py\nread spans + trace metadata",
            size=13,
        )
    )

    optimizer = rect(680, 450, 500, 80, fill="#d0bfff")
    els.append(optimizer)
    els.append(
        label(
            optimizer,
            "optimize_prompts (GEPA)\npulls +1 feedback, promotes @production",
            size=13,
        )
    )

    # Feedback-loop arrows back to root (trace as the source of truth)
    els.append(arrow((350, 450), (350, 162), dashed=True))
    els.append(arrow((930, 450), (930, 162), dashed=True))

    return els


def main() -> None:
    data = {
        "type": "excalidraw",
        "version": 2,
        "source": "coco-reference / docs/design/diagrams/_generate_mlflow_trace_structure.py",
        "elements": build_elements(),
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    out = Path(__file__).with_name("mlflow-trace-structure.excalidraw")
    out.write_text(json.dumps(data, indent=2))
    print(f"wrote {out} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
