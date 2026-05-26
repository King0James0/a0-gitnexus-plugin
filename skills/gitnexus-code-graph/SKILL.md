---
name: gitnexus-code-graph
description: Understand a codebase with GitNexus — index a repo, then find a symbol's callers and the blast radius/impact of a change, map structure, and run graph (Cypher) queries. Use when the user asks "what depends on X", "what's the blast radius of editing Y", "where is Z called", "index/analyze this repo", "map this repo", or before editing unfamiliar code.
---

# GitNexus code-graph

The `gitnexus` plugin installs the GitNexus CLI and registers its MCP server. GitNexus splits
the work in two: a **CLI step indexes** a repo, and the **MCP tools query** what's indexed.

## Index first (required — the MCP tools only query already-analyzed repos)

"No indexed repositories" just means nothing has been analyzed yet. To index:

1. **Make sure the repo is present locally.** If it's remote, clone it first:
   ```bash
   git clone <url> <dir>
   ```
2. **Analyze it with the CLI** (run in the terminal via code_execution_tool — `gitnexus` is on
   PATH; this is a CLI command, NOT one of the MCP tools):
   ```bash
   gitnexus analyze <path-to-repo>
   gitnexus list          # confirm it's now indexed
   ```

## Query (once indexed — use the gitnexus MCP tools)

3. **Before editing a symbol** — query its **callers** and **impact** (blast radius) to see what
   depends on it.
4. **To understand structure** — use the context / route-map / tool-map tools for the area.
5. **Ad-hoc** — run a graph (Cypher) query.

## Rules

- Index BEFORE querying; if a query returns nothing, check `gitnexus list` — the repo may not
  be analyzed yet.
- Query the graph before editing unfamiliar code; let the dependents guide how careful to be.
- Prefer narrow, targeted queries (one symbol/file/repo) over dumping the whole graph.
- Report findings as "X is called by A, B, C; editing it affects N dependents" — actionable,
  not raw query output.

## Failure handling

- No gitnexus tools in the toolset -> the MCP server isn't connected (check Plugins/MCP status;
  `gitnexus` must be on PATH; a restart re-runs setup).
- Empty results despite a real repo -> it isn't indexed; run `gitnexus analyze <path>` then retry.
- The exact MCP tool names come from the server — list/inspect the available `gitnexus` tools
  if unsure which to call.
