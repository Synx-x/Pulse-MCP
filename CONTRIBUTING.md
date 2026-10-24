# Contributing

## Run the tests

```sh
python3 -m pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The suite is `unittest`, so it needs no extra dependency. `tests/test_observe_live.py`
skips unless a browser answers on its reserved port. A skip is expected, not a
failure.

Check the source compiles before you push:

```sh
python3 -m compileall -q src tests
```

## What a patch must carry

A change to the screen map needs a test that fails without it. A change to the
browser or desktop adapter needs either a test or a recorded observation showing
the behaviour it fixes, because most adapter defects appear only against a real
page.

Name the case that prompted the change in the test. `test_a_scrolled_position_gets_its_own_screen_id`
says what broke. `test_5` does not.

## Rules the adapters follow

These exist because each one fixes a defect a real site exposed.

- **Read until two reads agree.** An async page update otherwise records the
  pre-click screen, and route learning fails with `changed nothing`.
- **Take a checkbox label from its `<label>`.** A styled control hides its box at
  opacity 0 and still owns the click.
- **Fold the scroll offset into the screen id.** Two positions in one long page
  otherwise answer to one id, and a stale-screen check passes wrongly.
- **Report `selected` for a class or `aria-current`.** A selection held only in a
  class changes no text and no bounds, so the flag is the only evidence.
- **Map no form value.** A fill keeps its value out of every map, result and
  routine. The one exception is page-rendered text, and the README states it.

## What to leave out

Do not add a runtime package dependency. Pulse runs as a child process of a
harness, and a dependency tree is the difference between installing it and not.

Do not weaken a check to make a test pass. If a route stop is correct behaviour,
the test asserts the stop.

## Commits and releases

Write the commit message about the defect, not the file. Say what broke and what
the fix protects.

Keep `CHANGELOG.md` current under `## [Unreleased]`, and cut a version when the
change is user-visible. A release is three artefacts naming the same thing: the
version in `pyproject.toml`, the changelog section, and the tag.
