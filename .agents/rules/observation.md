# Observation and transitions

A route is only as good as the signal that an action landed.

## The rule

**A route needs an observable signal.** A screen id changes only when a mapped
anchor changes. A page that reports an action only in a `<p>` changes nothing
mapped, so the map looks unchanged and no transition is recorded.

**Poll until two reads agree.** A clicked page that updates asynchronously
records a transition on the second matching read, capped at four seconds. The
same polling covers keys, fills and scrolls.

**A chosen control reports `selected: true`.** When it carries a `selected`
class or `aria-current`, that flag is the only evidence the click landed,
because such a control changes no text and no bounds.

**Read a styled checkbox through its label.** A control at opacity 0 still owns
the click, so the observer reads its text from the `<label>` and then skips that
label as a separate anchor.

## Why

**This has bitten before.** The demoqa buttons page writes "You have done a
dynamic click" into a paragraph. The map did not change after the action, so a
replay looked like it succeeded while the page had already responded. React App
Lab exposed the opposite case: a control whose only sign of success was a
`selected` class, invisible to a text or bounds diff.

## Source

- `src/pulse/screen_map.py` — anchors, transitions, shortest route
- `src/pulse/drivers/browser.py` — the settle loop and chosen-state read
- `docs/benchmark.md` — measured page behaviour behind each rule
