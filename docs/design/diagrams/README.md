# Diagrams

[Excalidraw](https://excalidraw.com) source files for the architecture
diagrams in this repo.

## Files

Every diagram here has a `.excalidraw` (editable source) and a `.svg`
(render output). Docs in the repo reference the `.svg` directly.

| Source | Render | What it shows |
|---|---|---|
| `request-flow.excalidraw` | `request-flow.svg` | End-to-end request flow: browser to Databricks App to dspy.ReAct agent, with Lakebase, MLflow, and the three tool surfaces (FMAPI / SQL warehouse / Vector Search). Also aliased as `apps-mosaic-ai-reference.svg` for the design doc. |
| `eval-architecture.svg` | `eval-architecture.svg` | The four loops on one MLflow experiment: production, observability, evaluation, optimization. |
| `mlflow-trace-structure.svg` | `mlflow-trace-structure.svg` | One agent invocation as a span tree: `react_agent` root, `dspy.ReAct.forward` child, five `@mlflow.trace` tool spans. |
| `lakebase-schema.svg` | `lakebase-schema.svg` | The four Lakebase tables (`threads`, `messages`, `runs`, `feedback`) and their FK relationships. |

Color coding, if you want to match it when adding a new diagram: blue `#228be6` for the browser/API layer, indigo `#3b5bdb` for the main agent, light blue `#5c7cfa` for storage and utility boxes, green `#40c057` or teal `#12b886` for outputs, gray `#868e96` for passive/dashed flows. Text is always `#f8f9fa` on these fills. Clean lines (roughness 0), Helvetica, 8px grid.

## How to open / edit

1. Go to https://excalidraw.com
2. **File -> Open**, pick the `.excalidraw` file
3. Edit visually. When you save, overwrite the file in place.

Diagrams in this directory are **source** - raw Excalidraw JSON, not
rendered images. To embed a diagram in a markdown doc, export a PNG
or SVG from excalidraw.com (File -> Export image) and reference that
alongside the source. The `.excalidraw` file stays in git; the
exported image doesn't need to.

## How the source files were generated

The initial layouts were produced by small Python scripts named
`_generate_*.py` in this directory. They exist so the first pass is
reproducible - regenerate by editing the script and re-running, if
you want to rebuild the geometry from scratch. After that, visual
polish happens in excalidraw.com.
