# GitNexus for Agent Zero

Gives Agent Zero code-graph superpowers by installing the [GitNexus](https://www.npmjs.com/package/gitnexus) CLI and registering its MCP server, so the agent can analyze a codebase — dependencies, impact/blast-radius, symbol callers, route/tool maps, and ad-hoc graph (Cypher) queries — before it changes anything.

## What it can do

- **Code-graph queries** (`gitnexus-code-graph` skill) — once enabled, GitNexus's MCP tools appear in the agent's toolset: list indexed repos, find a symbol's callers, gauge the blast radius of an edit, map routes/tools, and run Cypher queries over the graph.
- **Visual code graph in the Canvas** (`gitnexus-canvas-view` skill) — adds a **GitNexus** icon to Agent Zero's right-side Canvas rail. Click it to explore an indexed repository's graph (symbols, dependencies, execution flows), file tree, and AI explorer right inside Agent Zero. Because GitNexus's web UI is local-only (it talks to its server over `localhost`), the plugin renders it in a **headless Chromium inside the container** and streams that view to the Canvas — everything stays on `127.0.0.1`, nothing is exposed externally. (Needs a Chromium in the environment; the plugin installs one via `apt` if none is present. The MCP tools work regardless.)

## Setup

1. **Install** via the Plugin Hub, a GitHub repo URL, or by uploading the plugin ZIP, then enable it in the **Plugins** list.
2. On first run the plugin installs the `gitnexus` CLI (`npm install -g gitnexus`) and registers `gitnexus mcp` as a stdio MCP server in Agent Zero's MCP settings. **Restart / re-enable** so the MCP server connects.
3. That's it — no API key. Ask something like *"what depends on this function?"* or *"map this repo"* and the agent will use the GitNexus tools.

> Requires Node.js/npm in the Agent Zero environment (present in the standard Docker image) and outbound network access on first run to install the CLI.

## How it works

The plugin registers a standard MCP server entry under Agent Zero's `mcp_servers` setting:

```json
"gitnexus": { "type": "stdio", "command": "gitnexus", "args": ["mcp"] }
```

Agent Zero spawns `gitnexus mcp` and exposes its tools to the agent. Because A0 reloads MCP automatically when that setting changes, the server connects without manual configuration.

## Configuration

`default_config.yaml` (override per scope in the plugin config UI):

| Key | Default | Meaning |
|---|---|---|
| `gitnexus_version` | `latest` | npm version of the gitnexus CLI to install, or a pinned version. |
| `mcp_server_name` | `gitnexus` | Key under `mcp_servers.mcpServers` this plugin registers. |
| `serve_port` | `4747` | Local port for the `gitnexus serve` graph web UI (what the in-container Chromium loads; bound to `127.0.0.1`). |
| `cdp_port` | `9223` | The headless Chromium's remote-debugging port that the screencast bridge connects to. |
| `bridge_port` | `14601` | The screencast bridge port registered with A0's Canvas gateway. |

## Uninstalling

Uninstall through the **Plugins UI**. The uninstall hook removes the gitnexus entry from your `mcp_servers` setting (Agent Zero reloads MCP) and, **if this plugin installed the gitnexus CLI, uninstalls it too** — so nothing is left behind. A `gitnexus` you had installed independently beforehand is left untouched. (A manual `rm -rf` of the plugin folder bypasses this hook — always uninstall via the UI for a clean removal.)

## Citing

If you use this in your work, please cite it (use the **"Cite this repository"** button on GitHub, or):

```bibtex
@misc{a0gitnexusplugin2026,
  title        = {a0-gitnexus-plugin: GitNexus code-graph for Agent Zero},
  author       = {King0James0},
  year         = {2026},
  howpublished = {\url{https://github.com/King0James0/a0-gitnexus-plugin}},
  note         = {GitHub repository}
}
```

## License

MIT — see [LICENSE](LICENSE).
