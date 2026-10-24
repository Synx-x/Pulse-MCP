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

## The four defects the live sites exposed

Date: 2026-10-24. Six workflows on public sites drove four fixes. Each defect
stopped a real route, and each now has a test.

| Defect | Symptom | Fix |
| --- | --- | --- |
| Styled checkbox hidden at opacity 0 | TodoMVC's per-item toggle never mapped, so no route could click it | The observer takes the control's text from its `<label>` and keeps the hidden box when the box hit-tests to itself |
| Async page update after a click | The dynamic-controls page recorded the pre-click screen, and route learning failed with `changed nothing` | Every action reads until two reads agree on one screen id, bounded at 4 s, or 0.6 s while the screen is unchanged |
| Stale check built the id without the scroll offset | A click on any scrolled page always failed as stale | The click calls the same `screen_id_at` the rest of the service uses |
| Selection held only in a CSS class | The React App Lab outline click changed no text and no bounds, so it looked like a no-op | The observer reports a `selected` class or `aria-current` as `selected: true` |

Step count sets the gain. Six clicks on the add/remove page, in process, 3 trials
each: baseline p50 4,328 ms, replay p50 1,177 ms, a 72.8% reduction, with 3/3
correct end states on both paths. Each baseline step costs an observe plus a
guarded check. A route step costs one settled read. The gain stops short of 200%
because a replay step still waits for its screen.

The scroll route now passes 3/3 where it passed 2/3 before the settle wait. The
divergence it used to report came from reading the page too early.

## Two harnesses on the same six workflows

Date: 2026-10-24. Six workflows on public sites, 2 paired trials per path, ran
through both harnesses. The model was `deepseek-v4.1-flash-ultrafast` through
OpenGateway for both. Claude Code ran `2.1.310` headless against
`ANTHROPIC_BASE_URL=https://apis.opengateway.ai` with a dedicated config
directory. Codex ran `codex exec` with the same model. Every run got its own
Pulse state directory, its own Chromium profile and its own agent desktop.

Wall time is the CLI process wall clock, which includes process launch on both
paths. Success is read from the live page after the run, never from the agent's
own report.

The sequential workflow ran separately with 3 trials per path, on both harnesses.
Six clicks on the add/remove page:

| Harness | Tool calls base → replay | Baseline p50 | Replay p50 | Reduction | Success |
| --- | --- | ---: | ---: | ---: | --- |
| Claude Code | 13 → 3 | 57.4 s | 16.0 s | 72.1% | 3/3 both |
| Codex | 14 → 2 | 84.2 s | 20.9 s | 75.1% | 3/3 both |

### Claude Code

| Workflow | Tool calls base → replay | Baseline p50 | Replay p50 | Reduction |
| --- | --- | ---: | ---: | ---: |
| Complete a todo | 7 → 5 | 30.9 s | 24.2 s | 21.7% |
| Add two elements | 5.5 → 2.5 | 25.6 s | 14.6 s | 43.0% |
| Toggle a checkbox | 3 → 2.5 | 14.0 s | 14.6 s | −4.3% |
| Enable dynamic controls | 4 → 3 | 16.8 s | 20.2 s | −20.2% |
| Scroll a long page | 4 → 3.5 | 18.4 s | 22.6 s | −22.8% |
| Open the app-lab outline | 4 → 3.5 | 17.7 s | 18.1 s | −2.3% |

All 24 runs reached the expected end state, 12 of 12 on each path. Repeated
identical calls fell from 20 to 8.

### Codex

| Workflow | Tool calls base → replay | Baseline p50 | Replay p50 | Reduction |
| --- | --- | ---: | ---: | ---: |
| Complete a todo | 7 → 5.5 | 44.2 s | 41.0 s | 7.3% |
| Add two elements | 5 → 2 | 43.2 s | 25.0 s | 42.0% |
| Toggle a checkbox | 3 → 2.5 | 29.7 s | 26.3 s | 11.3% |
| Enable dynamic controls | 3 → 2 | 27.6 s | 26.0 s | 5.8% |
| Scroll a long page | 2.5 → 2.5 | 25.1 s | 36.8 s | −46.7% |
| Open the app-lab outline | 4.5 → 3 | 34.8 s | 39.9 s | −14.7% |

All 24 Codex runs reached the expected end state. Its overall p50 was 31.2 s
baseline and 28.2 s replay, a 9.3% reduction. Repeated identical calls fell from
18 to 5. Codex lost most on the scroll workflow, where one replay trial took
51.3 s against a 25.1 s baseline p50.

### What the paired runs do not show

The 200% target is unmet on every workflow here. The best measured case is the
six-click sequential workflow at 72.1% through Claude Code, 75.1% through Codex,
and 72.8% in process. The overall p50 across the six Claude workflows was 18.2 s
baseline and 18.6 s replay, a 2% regression, and three of six workflows were
slower on replay. The tool counts show why: on a single-step workflow a route
saves one call, and the settle wait on each replay step costs about what the saved
observation cost.

Reaching 200% would need replay to skip the per-step settle wait. That wait is
what makes an async step record correctly.

These numbers are CLI wall time, so launch overhead sits in both paths. They are
not a claim about steady-state agent latency.

A map can hold a typed value after the page renders it. Pulse keeps a fill's
value out of its own result and out of the map at fill time. TodoMVC then renders
the value as the row's checkbox label, and the observer maps that label like any
other page text. Redacting it would drop real page content, so the README states
the limit instead.
