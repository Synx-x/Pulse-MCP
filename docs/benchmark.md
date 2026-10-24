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
gain for Codex, desktop tasks, longer or visual-only flows, or live sites. A
model alias was not a reliable way to pin the backend in this CLI: the
successful alias-started baseline switched to Haiku 5.5, and a separate replay
attempt using the alias failed before any Pulse call. The included runs
therefore compare the recorded Haiku 5.5 backend on both sides, so they measure
Pulse and not a model choice.

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

## Two harnesses inside agent desktops

Date: 2026-10-24. Two workflows, 2 paired trials per path, ran through both
harnesses. Each harness ran in its own workspace pane, on its own agent desktop
from the Agent Desktops daemon, with its own Chromium profile, its own CDP port
and its own Pulse state directory per trial. The panes were full-size, and the
host focus stayed on the user's own workspace throughout. Every trial ended at
the expected end state, read from the live page.

| Workflow | Harness | Calls base → replay | Baseline p50 | Replay p50 | Speed increase | Success |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Six clicks, sequential | Claude Code | 14.5 → 3 | 49.97 s | 17.38 s | 187.5% | 4/4 |
| Six clicks, sequential | Codex | 13.5 → 2 | 85.03 s | 23.35 s | 264.2% | 4/4 |
| Two book categories | Claude Code | 5 → 3 | 19.73 s | 14.57 s | 35.3% | 4/4 |
| Two book categories | Codex | 4 → 2 | 36.45 s | 26.15 s | 39.4% | 4/4 |

This run moves the sequential workflow from 51.52 s and 48.41 s to 17.98 s and
16.78 s. That is below the 278.2% the same workflow reached when the bench
launched Claude by binary path, and the gap is the tool count. Replay used 3
calls here against 2 in that set, so one trial paid the schema load.

The random workflow reaches 35.3% here and 39.4% through Codex, against 23.3%
and 75.4% in the earlier nine-workflow set. Both random figures stay far below
the 200% target.

## Two harnesses on the same six workflows

Date: 2026-10-24. Six workflows on public sites ran through both harnesses, 2
paired trials per path. Claude Code ran `2.1.310` headless with a dedicated
config directory, and Codex ran `codex exec`. Both harnesses shared one model
through a hosted gateway. Each trial got its own Pulse state directory, its own
Chromium profile and its own agent desktop.

Wall time is the CLI process wall clock, which includes process launch on both
paths. Success is read from the live page after the run, never from the agent's
own report.

The sequential workflow is part of the nine-workflow set: 2 paired trials per
path, on both harnesses. Six clicks on the add/remove page:

| Harness | Tool calls base → replay | Baseline p50 | Replay p50 | Reduction | Speed increase | Success |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Claude Code | 16 → 2 | 43.63 s | 11.54 s | 73.6% | 278.2% | 2/2 both |
| Codex | 15.5 → 2 | 84.15 s | 22.37 s | 73.4% | 276.2% | 2/2 both |

An earlier run of this workflow, before replay began returning its final state,
recorded 57.4 s to 16.0 s through Claude Code and 84.2 s to 20.9 s through Codex.
The earlier set also used the older six-workflow list.

### Claude Code

Nine workflows, 2 paired trials per path, after replay began returning its final
state. Success is read from the live page after the run.

| Workflow | Tool calls base → replay | Baseline p50 | Replay p50 | Speed increase |
| --- | --- | ---: | ---: | ---: |
| Six clicks in a row | 16 → 2 | 43.63 s | 11.54 s | 278.2% |
| Two clicks | 6 → 3 | 16.91 s | 13.71 s | 23.3% |
| Open two book categories | 4 → 2 | 16.98 s | 12.19 s | 39.3% |
| Toggle a checkbox | 3 → 2 | 12.26 s | 9.78 s | 25.4% |
| Tick the Home tree node | 3 → 2 | 19.90 s | 12.09 s | 64.6% |
| Enable dynamic controls | 5 → 2 | 19.74 s | 12.29 s | 60.6% |
| Open the app-lab outline | 4 → 4 | 21.16 s | 15.65 s | 35.2% |
| Scroll a long page | 2 → 2 | 10.21 s | 13.62 s | −25.0% |
| Complete a todo | 6 → 6 | 18.77 s | 24.77 s | −24.2% |

Overall p50 was 17.83 s baseline and 12.49 s replay, a 42.8% speed increase. All
35 runs that started reached the expected end state. One further baseline trial
never ran, because route learning found no checkbox anchor named "Select Home"
on the demoqa page that day.

Two workflows regressed, and neither regression comes from replay. The todo
workflow pays the same fill-and-enter prefix on both paths, and the route covers
only the final click. The scroll workflow has a two-call route on both paths, so
a single trial that loads tool schemas first decides its timing.

### Codex

The same nine workflows, 2 paired trials per path, on the same day and the same
ports.

| Workflow | Tool calls base → replay | Baseline p50 | Replay p50 | Speed increase |
| --- | --- | ---: | ---: | ---: |
| Six clicks in a row | 15.5 → 2 | 84.15 s | 22.37 s | 276.2% |
| Two clicks | 5 → 2 | 36.86 s | 21.02 s | 75.4% |
| Open two book categories | 4.5 → 2 | 37.33 s | 23.70 s | 57.5% |
| Toggle a checkbox | 3 → 2 | 25.98 s | 22.17 s | 17.2% |
| Tick the Home tree node | 3 → 2 | 27.76 s | 23.02 s | 20.6% |
| Enable dynamic controls | 3 → 2 | 26.23 s | 22.16 s | 18.3% |
| Open the app-lab outline | 4.5 → 3 | 36.05 s | 30.11 s | 19.7% |
| Scroll a long page | 2.5 → 2 | 24.43 s | 21.74 s | 12.4% |
| Complete a todo | 7 → 5 | 44.73 s | 35.39 s | 26.4% |

Overall p50 was 34.55 s baseline and 23.00 s replay, a 50.2% speed increase. All
36 runs reached the expected end state. Replay dropped to 2 calls on seven of the
nine workflows.

Codex pays a higher launch floor than Claude Code, 11.4 s against 5.7 s, so its
smaller absolute savings still beat Claude Code on the sequential workflow and
across the whole set. Codex spent 13 to 18 calls on a six-click baseline, where
Claude Code spent 13 to 16.

### Unseen sites, second batch

Date: 2026-10-24. Two workflows on sites no earlier run had used. Each harness ran
2 paired trials per path, inside its own agent desktop and Chromium profile.

| Workflow | Site | Harness | Tool calls base → replay | Baseline p50 | Replay p50 | Reduction | Success |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| Open two categories in a row | books.toscrape.com | Claude Code | 5.5 → 2.5 | 25.0 s | 13.4 s | 46.4% | 2/2 both |
| Open two categories in a row | books.toscrape.com | Codex | 5 → 2 | 35.2 s | 21.0 s | 40.4% | 2/2 both |

A route needs a mapped anchor to change. On demoqa.com/buttons a click writes
"You have done a dynamic click" into a `<p>`, the observer maps no paragraph, so
the screen id held and the route learned nothing. The README states that gap, and
the demoqa checkbox page replaced this candidate. Its route verified first try.

### What the paired runs do not show

The 200% goal measures a speed increase. Speed increase divides baseline by
replay before subtracting one, and reduction divides the saved time by the
baseline. The six-click sequential workflow speeds up by 278.2% through Claude
Code, which moves 43.63 s to 11.54 s and cuts the time by 73.6%. The sequential
half of the goal is met through both harnesses. Codex speeds up by 276.2% on the
same workflow, and the in-process path speeds up by 267.7%.

Claude Code falls short on random and single-step requests. Two clicks through
Claude Code reach a speed increase of 23.3% in the current set, and 75.3% in the
earlier set. The earlier baseline re-observed before each action, so the two sets
remove different amounts of observation for that agent. A single step regressed
in two of nine workflows. The overall p50 across the nine Claude workflows was
17.83 s baseline and 12.49 s replay, a speed increase of 42.8%.

Codex clears random requests and misses on single steps. Two clicks through Codex
reach 75.4%, and two book categories reach 57.5%. Its single-step workflows reach
12.4% to 20.6%. The overall p50 across the nine Codex workflows was 34.55 s
baseline and 23.00 s replay, a speed increase of 50.2%.

Both harnesses reach the sequential target, and neither reaches it on random or
single-step requests.

The settle wait sets a replay step's cost, and the reads inside it are cheap. One
settled read costs about 4.6 ms on an unchanged page. The settle call that wraps
it costs 631 ms. The launch floor is 5.7 s for the Claude CLI and 11.4 s for
Codex. Either path pays that floor, so a short workflow is mostly overhead.

Replay no longer pays a confirmation turn. Replay returns the final state it
already read, so the agent does not call observe a second time. Replay uses fewer
calls than its baseline on seven of the nine workflows, and six workflows reach 2
calls on replay.

Closing the remaining gap would need replay to skip the per-step settle wait.
That wait is what makes an async step record correctly, so the trade is a
correctness decision rather than a tuning one.

These numbers are CLI wall time, so launch overhead sits in both paths. They are
not a claim about steady-state agent latency.

A map can hold a typed value after the page renders it. Pulse keeps a fill's
value out of its own result and out of the map at fill time. TodoMVC then renders
the value as the row's checkbox label, and the observer maps that label like any
other page text. Redacting it would drop real page content, so the README states
the limit instead.

### Two ways this bench corrupted its own runs

Both corruptions came from a second page taking over the port a trial was using.
Each one produced a trial that looked like a product failure.

The first corruption came from a probe browser. A probe on the bench port
navigated the page under test between two trials, so a click hit a screen from a
different task. The harness now refuses to start a probe browser on a bench port.

The second corruption came from the test suite. `tests/test_observe_live.py`
defaulted to port 9299 and navigated whatever browser answered it, writing a
"Fixture" page over the bench page. Runs then observed `about:blank` and refused
the task, which is correct behaviour on the page they actually saw. The live test
now skips a reserved port, so a suite run can never take over a trial.

The product fix that came out of both: a browser call takes an optional
`target_url`, so one CDP port with several tabs stays on the page under test.
`pulse_browser_targets` lists the tabs and the one a call would choose. A failed
screenshot capture on a background tab now reports no digest instead of losing
the whole observation.
