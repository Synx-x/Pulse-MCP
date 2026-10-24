# Security

## Report a vulnerability

Open a private security advisory at
https://github.com/Synx-x/pulse/security/advisories/new.

Do not open a public issue for a vulnerability. A public issue tells everyone
before a fix exists.

## What Pulse holds, and what it never holds

Pulse stores a screen map and saved routines under the state directory. A map
holds roles, labels, selected state, normalized bounds and a screenshot digest.
A map never holds form values or screenshot bytes, and a URL loses its query and
fragment before storage. Map and routine files are written atomically with
owner-only permissions.

**One path does leak a typed value.** A typed value stays out of every map, tool
result and routine. A typed value reaches the map anyway when the page displays
it, because Pulse maps page text as an anchor label. A typed value never belongs
in a secret field whose page shows it. TodoMVC shows exactly that case.

## What Pulse can do to your machine

Pulse drives a browser through a local Chromium DevTools endpoint, and a desktop
through `computer-use-linux`. Both act on real input.

- A browser call needs a mapped screen and an explicit `authorized_effects`
  declaration for a control classified as a write. A stale screen id stops the
  action.
- A fill refuses password, file, hidden, checkbox, radio, disabled and read-only
  fields, and sends no key, so a fill cannot submit a form.
- Replay verifies each expected state and stops on divergence rather than
  acting on an unexpected screen.

Pulse opens no listening port. It speaks MCP over stdio, so a harness launches
it as a child process and nothing stays running between sessions.

## Scope

Pulse is not a sandbox. It acts with the permissions of the machine account that
launched it, against whatever browser profile and desktop it is pointed at.
Connect only a browser profile you intend an agent to control.
