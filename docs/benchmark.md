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
evidence for this browser case. Next benchmark gates are the same paired test
through the actual harness and representative production workflows, followed
by a desktop adapter benchmark. Keep the 50% project target open until those
workloads pass without a success-rate regression.
