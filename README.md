# GitNexus for Agent Zero

Gives Agent Zero code-graph superpowers by installing the [GitNexus](https://www.npmjs.com/package/gitnexus) CLI and registering its MCP server, so the agent can analyze a codebase — dependencies, impact/blast-radius, symbol callers, route/tool maps, and ad-hoc graph (Cypher) queries — before it changes anything.

## Support

If this plugin is useful to you, you can support the developer.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/king0james0) [![Solana](https://img.shields.io/badge/Solana-9945FF?style=for-the-badge&logo=solana&logoColor=white)](https://solscan.io/account/HXrzPqgcxBR9LctTVdTF6xCLpah4hQwyYEevsQ98QvTo) [![Ethereum](https://img.shields.io/badge/Ethereum-3C3C3D?style=for-the-badge&logo=ethereum&logoColor=white)](https://etherscan.io/address/0xfF61681F907fA8DB39C1d23cbdbE89D24A94De17) [![Bitcoin](https://img.shields.io/badge/Bitcoin-F7931A?style=for-the-badge&logo=bitcoin&logoColor=white)](https://mempool.space/address/bc1qyr6x7kmxpy6ke0xutkxg90f30658fnr39h0d7r)

## What it can do

- **Code-graph queries** (`gitnexus-code-graph` skill) — once enabled, GitNexus's MCP tools appear in the agent's toolset: list indexed repos, find a symbol's callers, gauge the blast radius of an edit, map routes/tools, and run Cypher queries over the graph.
- **Visual code graph in the Canvas** (`gitnexus-canvas-view` skill) — adds a **GitNexus** icon to Agent Zero's right-side Canvas rail. Click it to explore an indexed repository's graph (symbols, dependencies, execution flows), file tree, and AI explorer right inside Agent Zero. Because GitNexus's web UI is local-only (it talks to its server over `localhost`), the plugin renders it in a **headless Chromium inside the container** and streams that view to the Canvas — everything stays on `127.0.0.1`, nothing is exposed externally. (Needs a Chromium in the environment; the plugin installs one via `apt` if none is present. The MCP tools work regardless.) The repo list **auto-refreshes**: when you index or re-index a repo, the surface reloads itself within a couple of seconds (and on open) so the new/updated repo appears — no manual refresh, and the code word-wrap is preserved. The reload only happens when the index actually changed, so it won't disturb your view otherwise. You can also **select text in the surface and `Ctrl/Cmd+C`** to copy it to your own machine's clipboard (the code view and detail panels are made selectable for this), and **`Ctrl/Cmd+V`** to paste your local clipboard into a field on the surface. It's cross-platform; copying uses the async Clipboard API on `https`/`localhost` with a legacy fallback for plain-`http` LAN access.
- **Scheduled re-index** — keeps your indexed graphs fresh. Opt-in (off by default) — turn it on and the plugin registers a recurring Agent Zero scheduled task (**"GitNexus re-index"**, Sundays 06:00 by default) that re-runs `gitnexus analyze` on any repo you've **already** indexed whose latest commit has changed since it was last indexed. It does **not** discover or index new repos — that's your call. See [Keeping indexes fresh](#keeping-indexes-fresh).

## Setup

1. **Install** via the Plugin Hub, a GitHub repo URL, or by uploading the plugin ZIP, then enable it in the **Plugins** list.
2. On first run the plugin installs the `gitnexus` CLI (`npm install -g gitnexus`) and registers `gitnexus mcp` as a stdio MCP server in Agent Zero's MCP settings. **Restart / re-enable** so the MCP server connects.
3. That's it — no API key. Ask something like *"what depends on this function?"* or *"map this repo"* and the agent will use the GitNexus tools.

> Requires Node.js/npm in the Agent Zero environment (present in the standard Docker image) and outbound network access on first run to install the CLI.

> **Note on `onnxruntime-node`:** gitnexus pulls in `onnxruntime-node` for its *optional* local-embeddings (`--embeddings`) feature, and that dependency's native installer downloads a NuGet runtime that fails to unpack in some environments — which would otherwise abort the whole CLI install. The plugin doesn't use embeddings, so it installs gitnexus with `ONNXRUNTIME_NODE_INSTALL=skip`: only that one optional download is skipped, while gitnexus's required native pieces (its graph-DB engine and language grammars) build normally. You get a fully working CLI (MCP, analysis, Canvas, all core languages), just without local embeddings.

## How it works

The plugin registers a standard MCP server entry under Agent Zero's `mcp_servers` setting:

```json
"gitnexus": { "type": "stdio", "command": "gitnexus", "args": ["mcp"] }
```

Agent Zero spawns `gitnexus mcp` and exposes its tools to the agent. Because A0 reloads MCP automatically when that setting changes, the server connects without manual configuration.

## Keeping indexes fresh

A GitNexus index is a snapshot — it reflects a repo at the commit it was analyzed at, so it drifts out of date as you keep committing. To keep it current the plugin can register a scheduled task — **opt-in, off by default.** Turn `reindex.enabled` on in the plugin config and the task is registered; turn it off and it's removed — the toggle takes effect immediately, no restart:

- **Task name:** `GitNexus re-index` (visible and editable under Agent Zero's **Scheduler**).
- **Default schedule:** Sundays at 06:00, in Agent Zero's configured timezone.
- **What it does each run:** reads the GitNexus registry and, for every repo you've already indexed that is a git work-tree, compares the repo's current `HEAD` against the commit it was last indexed at. If they differ, it runs an incremental `gitnexus analyze` on that repo; if not, it skips it (so an idle week does almost no work).
- **What it does *not* do:** it never indexes new repos. You decide what to index (`gitnexus analyze <path>`); the task only keeps current what you already chose.

### How it's wired

The work and the schedule are deliberately separated:

- **A deterministic helper does all the work.** `helpers/reindex.py` is plain Python — it reads the registry, does the commit comparison, and runs `gitnexus analyze` on the repos that changed. No model/LLM is involved in the indexing logic itself.
- **The scheduled task is purely the visible trigger.** The `GitNexus re-index` task carries no logic; its instruction is just *"run `helpers/reindex.py` and report the summary."* It exists so the schedule is something you can see, edit, disable, or delete from the Scheduler UI.
- **Triggering goes through the agent loop.** Agent Zero runs every scheduled task by handing its prompt to the agent (that's the only execution path A0 has), so when the task fires the agent's single action is to run the helper via its code-execution tool. There is **no background thread** — nothing runs the helper except this task, so it never double-fires.
- **Cost:** because the trigger passes through the agent, each run spends a small amount of the model's budget on that one "run this command" hop — *not* on the indexing, which is the deterministic helper's job.

### Editing the schedule

Change the cadence, time, or timezone whenever you like — once the task exists the plugin never overwrites your edits, and re-enabling won't recreate a task you've edited (turning `reindex.enabled` off removes it):

1. Open Agent Zero and go to the **Scheduler** (the tasks/clock panel).
2. Find the task named **`GitNexus re-index`** and open it for editing.
3. Edit the **schedule** — it's a standard 5-field crontab (`minute hour day month weekday`). Examples:
   - `0 6 * * 0` — weekly, Sundays at 06:00 (the default)
   - `0 3 * * *` — every day at 03:00
   - `0 */6 * * *` — every 6 hours
4. Set the **timezone** if you want it to differ from Agent Zero's default.
5. **Save.** The new schedule takes effect immediately. To run it right now, use the task's **Run** action — it executes the same helper on demand.
6. To pause it, **disable** the task; to stop it entirely, **delete** it. To turn it off at install time instead, set `reindex.enabled: false` in the plugin config; to change the install-time default schedule, edit `reindex.schedule` there.

**Limitations:** repos indexed with `--skip-git` (or non-git folders) have no commit to compare, so they aren't auto-refreshed; re-index those manually.

## Configuration

`default_config.yaml` (override per scope in the plugin config UI):

| Key | Default | Meaning |
|---|---|---|
| `gitnexus_version` | `latest` | npm version of the gitnexus CLI to install, or a pinned version. |
| `mcp_server_name` | `gitnexus` | Key under `mcp_servers.mcpServers` this plugin registers. |
| `serve_port` | `4747` | Local port for the `gitnexus serve` graph web UI (what the in-container Chromium loads; bound to `127.0.0.1`). |
| `cdp_port` | `9223` | The headless Chromium's remote-debugging port that the screencast bridge connects to. |
| `bridge_port` | `14601` | The screencast bridge port registered with A0's Canvas gateway. |
| `reindex.enabled` | `true` | Register the scheduled re-index task on install. Set `false` to skip it. |
| `reindex.schedule` | Sun 06:00 | Install-time crontab default (`minute`/`hour`/`day`/`month`/`weekday`). Edit the task in the Scheduler UI to change it after install. |
| `reindex.timezone` | `""` | Timezone for the schedule; empty uses Agent Zero's configured timezone. |

## Uninstalling

Uninstall through the **Plugins UI**. The uninstall hook removes the `GitNexus weekly re-index` scheduled task, removes the gitnexus entry from your `mcp_servers` setting (Agent Zero reloads MCP) and, **if this plugin installed the gitnexus CLI, uninstalls it too** — so nothing is left behind. Your indexed repos and their `.gitnexus` data are left untouched. A `gitnexus` you had installed independently beforehand is left untouched. (A manual `rm -rf` of the plugin folder bypasses this hook — always uninstall via the UI for a clean removal.)

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
