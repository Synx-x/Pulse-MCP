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
