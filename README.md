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

The browser and desktop adapters are the next layer. Until those adapters land,
an agent uses its existing browser or computer-use MCP to observe a screen, then
passes the accessibility/DOM/visual anchors to Pulse. Pulse's route output is
deterministic and uses only transitions marked verified.

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

Anchor bounds are normalized: `x`, `y`, `width`, and `height` each use the
viewport as a 0–1 scale. An anchor is placed in the grid cell containing its
center. Transitions become route-eligible only after the caller marks them
verified. Write and irreversible effects are recorded as metadata; no action
is executed by the current MCP server.

## Development checks

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

## Performance target

Pulse aims for at least 50% lower median end-to-end time than a model-in-the-loop
computer-use baseline, with verified success preserved. This repository has no
live benchmark result yet. The gate is repeated, paired runs on browser and
desktop tasks, with task success, false success, side effects, wall time, model
calls, retries, and fallback recorded for every run.
