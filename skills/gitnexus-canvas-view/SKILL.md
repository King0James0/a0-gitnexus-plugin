---
name: gitnexus-canvas-view
description: Show GitNexus's interactive code-graph web UI in Agent Zero's right-side Canvas. Use when the user wants to SEE a repository's code graph visually — nodes, edges, execution flows, the file tree, the AI explorer — rather than just query it via the MCP tools (that's gitnexus-code-graph).
---

# View the GitNexus code graph in the Canvas

The `gitnexus` plugin adds its own **GitNexus** surface to the right-side Canvas rail (next to
Browser, Desktop, Editor, Obsidian). Opening it shows GitNexus's live web UI — pick an indexed
repository and explore its code graph (symbols, dependencies, execution flows) interactively.

## How to show it

Surfaces are opened by the **user** from the UI, not by a tool call. So:

1. Tell the user: open the right-side **Canvas** and click the **GitNexus** icon in the rail.
2. It starts the GitNexus web UI (a couple of seconds the first time), then shows a repository
   picker. Click an indexed repo to open its graph; use the filters and the explorer to navigate.

## Rules

- You cannot click the surface open yourself — guide the user to the **GitNexus** icon in the
  Canvas rail.
- The surface only lists repositories that have already been **indexed**. To index one, run
  `gitnexus analyze <path>` in the terminal first (a local clone; clone a remote repo first) — see
  the `gitnexus-code-graph` skill. Newly indexed repos appear in the picker.
- For programmatic answers (callers, blast-radius, Cypher, route/tool maps), use the GitNexus MCP
  tools via `gitnexus-code-graph` — the Canvas surface is for visual exploration, not for the
  agent to read data from.
