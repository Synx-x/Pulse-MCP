# Initial browser replay benchmark

Date: 2026-10-24. Host: Ryoku, local headless Chromium 153, isolated temporary
profile on CDP port 9234. Test page had four deterministic DOM states and three
button transitions. The map and verified route were learned before timing.

Each paired run began from the same page state. Timing wrapped MCP `tools/call`
dispatch in-process (not stdio or a hosted harness). The baseline used three
`pulse_browser_click` calls; each checked the current mapped state, clicked its
control, observed the result, and captured screenshot digests. Replay used one
`pulse_browser_replay` call; it checked the starting state, verified every DOM
state transition, and captured a screenshot digest only for the final state.
Seven runs were collected for each path. No external site or account data was
used. All 14 runs reached the expected final state; there were no unintended
effects in this local fixture.

| Path | p50 | Samples |
| --- | ---: | --- |
| Three guarded click calls | 309.0 ms | 321.4, 331.3, 297.7, 298.6, 300.0, 309.0, 316.0 |
| One verified route replay | 95.9 ms | 97.3, 92.2, 91.9, 96.0, 95.9, 96.2, 95.3 |

Median local driver latency fell 69.0%: `(1 - 95.9 / 309.0) × 100`. This is a
browser-driver microbenchmark, not total task time or Claude/Codex latency. It
does not include model thinking, tool transport through a hosted agent, desktop
accessibility, or visual-only tasks. Replay still validates every state; it
avoids intermediate screenshot encoding because the DOM map is the state
evidence for this browser case.

## Isolated desktop route

The Linux desktop adapter was tested in a temporary 960×720 headless Sway
desktop managed by the existing Agent Desktops service. A local GTK fixture had
three screens and two write controls. The map combined the CUL accessibility
tree with Sway window geometry; a Zenity probe with zero AT-SPI positions used
Tesseract to locate each button label separately. The two-step route was learned
with real clicks, reset outside the timed sections, then replayed. Seven runs
per path all reached the expected final screen.

| Path | p50 | Samples |
| --- | ---: | --- |
| Two guarded desktop click calls | 3,364.9 ms | 3,291.6, 3,261.1, 3,311.0, 3,384.1, 3,416.4, 3,732.0, 3,364.9 |
| One verified desktop replay | 1,047.7 ms | 1,022.6, 1,042.0, 1,019.3, 1,047.8, 1,088.5, 1,108.9, 1,047.7 |

Median local driver latency fell 68.9%: `(1 - 1,047.7 / 3,364.9) × 100`.
Replay reused the accessibility map and window geometry for this task, so it
needed no screenshots; maps that rely on vision anchors still capture a
screenshot to verify those anchors. This is an in-process MCP driver test, not
an end-to-end harness benchmark. It excludes model time, Herdr transport, and
other desktop applications. Next gates are paired runs through Claude/Codex on
representative browser and desktop workflows, with success preserved.

## Claude model-in-the-loop browser route

Date: 2026-10-24. The test used a dedicated temporary Chromium profile, a
loopback-only five-state page, and the local Pulse MCP server. Four sequential
button transitions led to “Workflow complete”; a reset control returned the
fixture to the same start state between trials. Pulse learned and verified the
route before timing. The saved map had six observed screens and five verified
edges (the four-step route plus reset), with each screen’s anchors placed on
the 8×12 grid.

The baseline agent observed the page and made four separately guarded
`pulse_browser_click` calls. In these runs Claude chose to re-observe between
clicks, for nine Pulse calls total. The replay agent made one
`pulse_browser_replay` call. Both paths used Claude Code with the same recorded
backend, Haiku 5.5; each of the three paired trials reached the same final
screen. The replay tool reported all four transitions verified.

| Measure | Four guarded clicks | One verified replay | p50 reduction |
| --- | ---: | ---: | ---: |
| Claude-reported duration | 42.757, 42.798, 40.364 s | 17.422, 16.483, 17.385 s | 59.3% |
| CLI process wall time | 47.046, 46.705, 44.242 s | 21.452, 20.313, 21.368 s | 54.2% |

These are three paired runs of one deterministic local browser route. Wall time
includes launching a fresh Claude CLI process on both sides. This is the first
model-in-the-loop result above the 50% target, but it does not establish that
gain for Codex, desktop tasks, longer or visual-only flows, or live sites. The
`ultrafast` model alias was not a reliable way to pin the backend in this CLI:
the successful alias-started baseline switched to Haiku 5.5, and a separate
replay attempt using the alias failed before any Pulse call. The included runs
therefore compare the recorded Haiku 5.5 backend on both sides; they are not a
DeepSeek UltraFast benchmark.

## Live public sites, four workflows

Date: 2026-10-24. The run used one isolated Chromium inside an agent desktop. The
run gave that Chromium its own profile, its own CDP port, and its own Pulse state
directory. The run placed the agent desktop on an isolated sway seat with a VNC
stream, so the host cursor and focus never moved. The run performed only
reversible actions: a fresh navigation between trials, a checkbox toggled back,
and a scroll that moves the viewport alone.

Each path ran three times per task. The baseline path performed one primitive per
step and re-observed before each step. The replay path performed the same clicks
as one verified route in a single call. The check read the live page after each
run, because a tool's own report is not evidence.

| Workflow | Site | Calls | Baseline p50 | Replay p50 | Reduction | Success |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Complete a todo | todomvc.com | 3 → 3 | 903.3 ms | 772.5 ms | 14.5% | 3/3 both |
| Add two elements | the-internet, add_remove_elements | 2 → 1 | 751.1 ms | 177.0 ms | 76.4% | 3/3 both |
| Toggle a checkbox | the-internet, checkboxes | 1 → 1 | 439.7 ms | 231.3 ms | 47.4% | 3/3 both |
| Scroll a long page | the-internet, infinite_scroll | 1 → 1 | 363.8 ms | 274.9 ms | 24.4% | 3/3, replay 2/3 |

The reduction tracks how much observation a route removes, not the click count.
The route that replaced several guarded steps gained the most. The route for a
single step gained the least, because both paths observe twice and a route saves
one intermediate screenshot digest.

Replay for the scroll route is the one incomplete result. Replay stopped on one
of three trials with `screen diverged; route stopped for replanning`, after zero
steps completed. A replay stop is correct behaviour rather than a silent wrong
answer. The lazy-loading page settled to a different screen id than the one
learned, and replay refused to act against it. Replay on this page needs a
settled-state wait before learning, and Pulse has none yet. A fixed pixel delta
across a page whose content height changes between runs is the cause.

Screen ids are the second result. Screen ids for the older scroll handling folded
no offset into the hash, so two positions in one long page answered to one id.
Screen ids that ignore the offset let a stale-screen check pass wrongly. Screen
ids now include the scroll offset, and
`test_a_scrolled_position_gets_its_own_screen_id` holds that property.
