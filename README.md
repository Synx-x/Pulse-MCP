# Pulse

Pulse gives computer-use agents a shared screen map and a place to save verified
workflows. It is a Python MCP server with no runtime package dependencies.

## Current slice

The MCP tools record screen observations from any driver, place their anchors on
a normalized 8×12 grid, connect screens with verified transitions, and return
the shortest verified route to a visible anchor or screen. Successful routines
can be saved as reviewable candidates. Pulse does not execute saved routines in
this version.

Screen observations contain roles, labels, normalized bounds, and a viewport
size. They do not contain form values or screenshot bytes. URLs have query and
fragment data removed before storage. Routine steps reject literal values;
use an `input_ref` and provide that value at execution time in a future driver.
Map and routine files are written atomically with owner-only permissions.

The browser adapter observes a Chromium page through its local DevTools
endpoint. It records visible DOM controls, roles, labels, selected state, and
viewport-relative bounds; it stores only a screenshot digest, never screenshot
bytes. Browser clicks require a current mapped screen and explicit effect
authorization for controls classified as writes. A changed screen records a
verified transition. Desktop observation and action adapters are still pending.
Once a route has been learned, `pulse_browser_replay` executes it in one MCP
call, verifies each expected DOM state, and stops on divergence. It captures a
screenshot digest for the final state only; intermediate route checks use the
structured DOM map.

## Install for development

```sh
python3 -m pip install -e .
pulse-mcp
```

The default data directory is `~/dev/pulse-data` when `~/dev` exists, otherwise
`$XDG_STATE_HOME/pulse` (or `~/.local/state/pulse`). Set `PULSE_STATE_DIR` to
choose another directory.

## Connect as an MCP server

For Claude Code, install the package and run:

```sh
claude mcp add --scope user pulse -- pulse-mcp
```

For Codex, add this to `~/.codex/config.toml`:

```toml
[mcp_servers.pulse]
command = "pulse-mcp"
```

Restart the harness after adding the server. Both harnesses expose the same MCP
tools; agents do not need a special Pulse command.

## Tools

| Tool | Purpose |
| --- | --- |
| `pulse_map_record_screen` | Save an observation and return its spatial grid |
| `pulse_map_record_transition` | Save a transition, marked verified or unverified |
| `pulse_map_get` | Read a whole map or one screen with its grid |
| `pulse_map_route` | Find a shortest route over verified transitions |
| `pulse_routine_save` | Save a successful routine as a candidate |
| `pulse_routine_list` | List candidates |
| `pulse_routine_get` | Read a candidate |
| `pulse_browser_observe` | Observe and map visible controls from a local Chromium tab |
| `pulse_browser_click` | Click a mapped control after a stale-screen check |
| `pulse_browser_replay` | Execute a verified route in one call with state checks |

Anchor bounds are normalized: `x`, `y`, `width`, and `height` each use the
viewport as a 0–1 scale. An anchor is placed in the grid cell containing its
center. Transitions become route-eligible only after they are observed to
change screen state. Browser controls are conservatively marked as writes and
require `authorized_effects: ["write"]` on a click. Clicks use native CDP mouse
input at the mapped control center; stale screen ids stop the action.

Start an isolated browser with remote debugging enabled. For a quick local test:

```sh
chromium --headless=new --no-sandbox --remote-debugging-port=9222 \
  --user-data-dir=/tmp/pulse-chromium about:blank
```

The server reads port 9222 by default; tools can pass another local debugging
port, or set `PULSE_CDP_PORT` in the MCP server environment. Connect only a
browser profile intended for agent control.

## Development checks

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

## Performance target

Pulse aims for at least 50% lower median end-to-end time than a model-in-the-loop
computer-use baseline, with verified success preserved. This repository has no
live harness-level benchmark result yet. An initial local Chromium driver test
is recorded in [docs/benchmark.md](docs/benchmark.md): a three-step fixture
route replay was 69.0% faster at p50 than three individual guarded clicks. This
does not include model thinking or agent transport. The gate is repeated, paired
runs on representative browser and desktop tasks, with task success, false
success, side effects, wall time, model calls, retries, and fallback recorded
for every run.
