# Diagrams

[Excalidraw](https://excalidraw.com) source files for the architecture
diagrams in this repo.

## Files

| File | What it shows |
|---|---|
| `request-flow.excalidraw` | CoCo v2 end-to-end request flow — user question through the Databricks App, Lakebase, agent serving endpoint, and into the LLM / SQL / VS / MLflow tool fanout. |

More to come. Until then, `docs/design/evaluation-architecture.md`
and `docs/design/apps-mosaic-ai-agent-reference.md` carry their
diagrams as Mermaid blocks embedded in the markdown.

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
