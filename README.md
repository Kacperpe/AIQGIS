# AIQGIS

AIQGIS is a QGIS 3.x plugin that adds an AI chat panel with access to the current project context and a growing set of QGIS/PyQGIS tools.

The current repository state matches version `0.11`.

## What Is Already Done

- Multi-provider AI support:
  Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, and LM Studio.
- Project-aware QGIS context:
  layers, CRS, active layer, selection, fields, and basic project metadata.
- Built-in QGIS tools for common operations:
  `select`, `filter`, `calculate field`, `buffer`, `clip`, `intersection`, `dissolve`, `reproject`, `save layer`, `zoom`, and `refresh`.
- Data inspection tools:
  layer listing, layer details, selection info, unique values, field summaries, attribute table paging, and expression-based attribute queries.
- A custom-task flow for non-trivial work:
  `inspect -> generate_pyqgis_code -> preview -> approve -> execute`.
- Inline action cards in the chat dock with session-based approvals:
  `Approve once`, `Approve for this command in session`, and `Always allow everything`.
- Response sanitization:
  model/tool artifacts are cleaned before anything is shown in chat.
- `insert_into_pyqgis_console` is no longer the default execution path.
  Code goes into the console only when the user explicitly chooses that action.
- A minimal `run_pyqgis_code` executor:
  controlled namespace, captured `stdout/stderr`, and basic detection of created or modified layers.

## Repository Layout

- `qgis_ai_assistant/`
  Current plugin source code.
- `previous_versions/`
  Older ZIP snapshots from earlier development stages.

## Installation

1. Copy the `qgis_ai_assistant` folder into your QGIS plugins directory.
2. Start QGIS and enable `AI Assistant for QGIS`.
3. Open the plugin panel and configure your AI provider.
4. Start with project/layer questions or run a task that requires a proposed action.

## Current Status

This is a working development-stage plugin, not a finished product.
The strongest parts right now are:

- provider integration
- project/data inspection
- session-based approval flow
- generation and execution of proposed PyQGIS actions from chat

## Current Limitations

- `run_pyqgis_code` is still experimental and is not a full security sandbox.
- There is no full risk-analysis pipeline yet.
- There are no hard execution timeouts yet.
- The UI is intentionally simple and focused on a working action flow rather than a final product design.
- The repository does not yet include a complete automated test suite.

## Previous Versions

Older ZIP packages were moved into `previous_versions/` so the repository root stays focused on the current source tree.
