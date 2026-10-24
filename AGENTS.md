# AGENTS.md

Canonical project guide. `CLAUDE.md` and `GEMINI.md` are five-line bridges that
import this file. Edit conventions here.

## What this is

A Python MCP server that gives computer-use agents a shared screen map and a
place to save verified workflows. A screen is a set of anchored controls on a
normalized grid. Screens connect by verified transitions. A route is the
shortest path over those transitions.

No runtime dependencies. Standard library only.

## Repo map

| Path | Holds |
|---|---|
| `src/pulse/server.py` | MCP tool definitions and dispatch |
| `src/pulse/service.py` | Map, route and routine logic |
| `src/pulse/screen_map.py` | The grid, anchors, transitions, shortest route |
| `src/pulse/store.py` | Atomic, owner-only persistence |
| `src/pulse/contracts.py` | The shapes a tool accepts and returns |
| `src/pulse/drivers/` | `browser`, `desktop`, `computer_use`, `cdp` |
| `tests/` | Unit tests plus live observation tests |

## Build and run

```bash
python3 -m pytest tests -q
pulse-mcp
```

## Golden rules

1. **A route needs an observable signal.** A page that reports an action only
   in a `<p>` changes no screen id, so the map looks unchanged. See
   `.agents/rules/observation.md`.
2. **A write control needs explicit authorization.** A click or fill that
   changes state is refused unless the caller names the effect. See
   `.agents/rules/safety.md`.
3. **A fill never submits.** The caller decides when a form goes. See
   `.agents/rules/safety.md`.
4. **Never store form values or screenshot bytes.** A mapped screen holds
   roles, labels, bounds, and a screenshot digest. URLs lose query and
   fragment before storage. See `.agents/rules/safety.md`.
5. **The screen must be current.** A click on a stale map is refused. A
   changed screen records a transition instead. See
   `.agents/rules/observation.md`.

## Rules index

| Working on… | Read |
|---|---|
| Mapping, transitions, replay | `.agents/rules/observation.md` |
| Guards, redaction, storage | `.agents/rules/safety.md` |
| Adding a driver | `.agents/rules/observation.md` |

## Coding style

Standard library only. Type hints on public functions. A docstring records the
measured behaviour and the page that prompted the rule, because every rule in
this repo came from one.
