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
verified transition.
A click reads the page again until two reads agree on one screen id, up to four
seconds. A clicked page that updates asynchronously otherwise records no
transition. The same polling covers keys, fills and scrolls.
A chosen control reports `selected: true` when it carries a `selected` class or an
`aria-current` attribute. Such a control changes no text and no bounds, so that
flag is the only sign the click landed. The React App Lab component outline works
this way.
The observer reads a checkbox or radio input's text from the `<label>` it belongs
to, then skips that label as a separate anchor. The observer does this because a
styled control hides its own box at opacity 0 and still owns the click. The
TodoMVC per-item toggle is the case that prompted this rule.
Once a route has been learned, `pulse_browser_replay` executes it in one MCP
call, verifies each expected DOM state, and stops on divergence. It captures a
screenshot digest for the final state only; intermediate route checks use the
structured DOM map.

The Linux desktop adapter reads `computer-use-linux` accessibility snapshots
and screenshots. It places accessible elements on the same normalized grid;
when an actionable element has missing or zero-position bounds, optional local
Tesseract OCR matches its accessible label to screenshot coordinates. Pulse
stores the screenshot digest and anchor metadata, not screenshot bytes or form
values. Desktop actions use the existing CUL input path. Browser and desktop
routes share the same verified-transition planner.

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
| `pulse_browser_fill` | Type into one mapped field, guarded, with no implicit submit |
| `pulse_browser_key` | Send `enter` or `escape` to the focused element |
| `pulse_browser_scroll` | Scroll the viewport by a bounded delta and re-map it |
| `pulse_browser_replay` | Execute a verified route in one call with state checks |
| `pulse_desktop_observe` | Map a Linux desktop from accessibility and screenshot data |
| `pulse_desktop_click` | Click a mapped desktop control after a stale-screen check |
| `pulse_desktop_replay` | Execute a verified desktop route with state checks |

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

A fill keeps the typed value out of every map, tool result, and saved routine. A
fill reports only the length it typed, and a fill refuses password, file, hidden,
checkbox, radio, disabled and read-only fields. A fill confirms the entry by
reading the field back, and a fill sends no key, so a fill cannot submit a form.
Two further rules govern focus and line endings:

- A fill drops focus once it confirms, because a focused field's text appears in
  the next observation's anchor labels. Pass `keep_focus` when a fill is followed
  by `pulse_browser_key`, which needs that focus for the key to land.
- A single-line field loses a trailing newline, so the entry is trimmed for that
  field and confirmed against the trimmed text.

A scroll position takes part in the screen id, so two positions in one long page
do not answer to the same id and a stale-screen check cannot pass wrongly. A
scroll that changes the screen records a verified transition, so the step can
join a route. `pulse_browser_replay` repeats that step from the deltas in its edge.

Desktop tools require `computer-use-linux mcp` on `PATH`; set
`PULSE_COMPUTER_USE_BIN` to choose a specific binary. Tesseract is optional and
is used only to place controls whose accessibility bounds are missing.

## Development checks

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

## Performance target

Replay latency aims at 50% below a model-in-the-loop computer-use baseline, with
verified success preserved. Replay latency on live public sites measured 76.4%
below the primitive path on a two-click workflow. Replay latency on live public
sites measured 14.5% to 47.4% below it on single-step and three-step workflows,
because a route saves observation work rather than click count. Replay latency
through Claude Code measured 54.2% below the baseline on p50 CLI wall time over
three paired runs of one local browser route, with all six runs succeeding.
Replay latency in-process measured 69.0% below it on a browser route and 68.9% on
a VNC-backed desktop route. Results and scope limits are in
[docs/benchmark.md](docs/benchmark.md). The harness-level result still needs
replication with Codex, desktop tasks, and more representative workflows. Track
task success, false success, side effects, wall time, model calls, retries, and
fallback for every run.
