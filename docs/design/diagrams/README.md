# Diagrams

[Excalidraw](https://excalidraw.com) source files for the architecture
diagrams in this repo.

## Files

Every diagram here has a `.excalidraw` (editable source) and a `.svg`
(render output). Docs in the repo reference the `.svg` directly.

| Source | Render | What it shows |
|---|---|---|
| `request-flow.excalidraw` | `request-flow.svg` | End-to-end request flow — browser to Databricks App to dspy.ReAct agent to the tool fanout (FMAPI / SQL warehouse / Vector Search / MLflow). |
| `apps-mosaic-ai-reference.excalidraw` | `apps-mosaic-ai-reference.svg` | The Apps + Mosaic AI reference architecture — one request through the stack with Lakebase and MLflow on the sides. |
| `eval-architecture.excalidraw` | `eval-architecture.svg` | Four loops on one MLflow experiment: production, observability, evaluation, optimization. |
| `mlflow-trace-structure.excalidraw` | `mlflow-trace-structure.svg` | One agent invocation as a span tree: `react_agent` root, five tool spans, LM sub-spans from `mlflow.dspy.autolog()`. |

## How to open / edit

1. Go to https://excalidraw.com
2. **File → Open**, pick the `.excalidraw` file
3. Edit visually. When you save, overwrite the file in place.

Diagrams in this directory are **source** — raw Excalidraw JSON, not
rendered images. To embed a diagram in a markdown doc, export a PNG
or SVG from excalidraw.com (File → Export image) and reference that
alongside the source. The `.excalidraw` file stays in git; the
exported image doesn't need to.

## How the source files were generated

The initial layouts were produced by small Python scripts named
`_generate_*.py` in this directory. They exist so the first pass is
reproducible — regenerate by editing the script and re-running, if
you want to rebuild the geometry from scratch. After that, visual
polish happens in excalidraw.com.
