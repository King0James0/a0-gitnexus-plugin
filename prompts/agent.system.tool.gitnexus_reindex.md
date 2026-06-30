## gitnexus_reindex
refresh the GitNexus code-graph index of already-indexed repos whose git HEAD moved (commit-aware, in-process)
- `gitnexus_reindex`: no arguments

notes:
- re-runs `gitnexus analyze` ONLY on repos already in the GitNexus registry whose HEAD changed since they were last indexed; it NEVER discovers or indexes new repos
- runs in-process (NOT through the terminal/code-execution tool) and returns a one-line summary (refreshed / skipped / fail counts); safe and idempotent
- this is what the scheduled "GitNexus re-index" task calls; you may also run it on demand. Call it at most once per request

example:
~~~json
{
  "thoughts": ["Refresh the GitNexus indexes for any repos whose code changed since last indexed."],
  "headline": "Re-indexing changed repos",
  "tool_name": "gitnexus_reindex",
  "tool_args": {}
}
~~~
