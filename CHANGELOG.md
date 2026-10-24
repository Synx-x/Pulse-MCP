# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

### Added

- The MCP surface: screen map recording, grid placement, verified transitions,
  shortest verified route, and routine candidates.
- Three drivers: `browser` over a local Chromium DevTools endpoint, `desktop`
  over accessibility and screenshot data, and `computer_use` over an external
  binary.
- Map and routine files written atomically, owner-only, with URLs stripped of
  query and fragment data before storage.
- Guarded writes: a click on a control classified as a write needs explicit
  effect authorization, and a fill never submits.
- `pulse_browser_replay` and `pulse_desktop_replay`, which execute a verified
  route and stop when the screen diverges.

### Known limits

- Pulse does not execute saved routines. They are reviewable candidates only.
- A page that reports an action only in a `<p>` changes no screen id, so the map
  looks unchanged after that action.
- A page that renders a filled value as its own visible text exposes that value
  as an anchor label.
