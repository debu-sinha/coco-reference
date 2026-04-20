"""Excalidraw source for the evaluation + optimization architecture.

Run: `python docs/design/diagrams/_generate_eval_architecture.py`
Output: `docs/design/diagrams/eval-architecture.excalidraw`

Shows the four loops that share the MLflow experiment:
production -> observability -> evaluation -> optimization.
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

    # Title
    els.append(text(260, 10, "CoCo — Evaluation + Optimization", size=22, width=600))
    els.append(text(260, 38, "four loops on one MLflow experiment", size=14, width=600))

    # Loop 1: Production (top-left)
    p_user = rect(60, 90, 220, 60, fill="#ffd8a8")
    els.append(p_user)
    els.append(label(p_user, "User asks a question"))

    p_agent = rect(60, 190, 220, 80, fill="#b2f2bb")
    els.append(p_agent)
    els.append(label(p_agent, "Agent answers\n(prompt @production)"))

    els.append(arrow((170, 150), (170, 188)))

    # Loop 2: Observability (top-right)
    o_trace = rect(360, 90, 240, 80, fill="#a5d8ff")
    els.append(o_trace)
    els.append(label(o_trace, "MLflow trace\n(every tool call, every LM)"))

    o_fb = rect(360, 210, 240, 60, fill="#a5d8ff")
    els.append(o_fb)
    els.append(label(o_fb, "Thumbs-up in Lakebase"))

    els.append(arrow((280, 230), (358, 230)))  # agent -> feedback
    els.append(arrow((280, 220), (358, 130)))  # agent -> trace

    # Loop 3: Evaluation (bottom-left)
    e_gold = rect(60, 350, 220, 60, fill="#d0bfff")
    els.append(e_gold)
    els.append(label(e_gold, "scenarios.yaml\ngolden set"))

    e_run = rect(60, 440, 220, 80, fill="#b2f2bb")
    els.append(e_run)
    els.append(label(e_run, "mlflow.genai.evaluate\n4 scorers"))

    els.append(arrow((170, 410), (170, 438)))

    # Loop 4: Optimization (bottom-right)
    opt_pull = rect(360, 350, 240, 60, fill="#ffc9c9")
    els.append(opt_pull)
    els.append(label(opt_pull, "Pull last 7d of +1 feedback"))

    opt_gepa = rect(360, 440, 240, 80, fill="#ffc9c9")
    els.append(opt_gepa)
    els.append(label(opt_gepa, "mlflow.genai.optimize_prompts\nGepaPromptOptimizer"))

    els.append(arrow((480, 270), (480, 348)))  # feedback -> pull
    els.append(arrow((480, 410), (480, 438)))  # pull -> GEPA

    # Registry (center-right, feeding production + GEPA output)
    reg = rect(680, 260, 260, 80, fill="#e599f7")
    els.append(reg)
    els.append(label(reg, "MLflow Prompt Registry\n@production alias"))

    els.append(
        arrow((940, 300), (280, 220), dashed=True)
    )  # registry feeds agent (dashed back-flow)
    els.append(arrow((600, 480), (810, 340)))  # GEPA -> registry (new version)
    els.append(arrow((810, 340), (810, 260)))  # tiny vertical hint that alias points at new version

    return els


def main() -> None:
    data = {
        "type": "excalidraw",
        "version": 2,
        "source": "coco-reference / docs/design/diagrams/_generate_eval_architecture.py",
        "elements": build_elements(),
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    out = Path(__file__).with_name("eval-architecture.excalidraw")
    out.write_text(json.dumps(data, indent=2))
    print(f"wrote {out} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
