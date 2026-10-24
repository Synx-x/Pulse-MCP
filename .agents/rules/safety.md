# Safety and storage

Pulse drives a real browser and a real desktop. Everything here limits the
damage a wrong call causes.

## The rule

**A write control needs explicit authorization.** A click or fill that changes
state is refused unless the caller names the effect in `authorized_effects`.
Read-only controls need nothing.

**A fill never submits.** Typing into a field leaves the form alone. The caller
decides when it goes.

**A stale map is refused.** A click on a screen the driver has not just
confirmed is rejected rather than applied to whatever is under the coordinate
now.

**Never store form values or screenshot bytes.** A mapped screen holds roles,
labels, normalized bounds, a viewport size and a screenshot digest. URLs lose
query and fragment data before storage.

**Files are atomic and owner-only.** Map and routine writes land mode 600 in a
mode 700 directory, via a temporary file and a rename, so a crash never leaves
a half-written map.

## Why

**This has bitten before.** A page that renders a filled value as its own
visible text exposes that value as an anchor label. Pulse cannot redact it
without dropping real page content, so the limit is stated in the README rather
than quietly failing. The lesson is that redaction belongs at the storage
boundary and the boundary has a documented edge.

Routine steps reject literal values for the same reason: a saved routine that
carries a password is a password in a JSON file. Use `input_ref` and supply the
value at execution time.

## Source

- `src/pulse/contracts.py` — where `authorized_effects` and `input_ref` are defined
- `src/pulse/store.py` — atomic write, permissions, URL stripping
- `README.md` — the stated limits, including the fill-as-text case
