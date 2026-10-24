"""Application operations used by the MCP transport."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Mapping

from .contracts import ScreenState, Transition, safe_id
from .screen_map import ScreenMap
from .store import Store
from .drivers.browser import FIELD_REJECTION_MESSAGES, BrowserDriver, field_rejection, redact
from .drivers.computer_use import ComputerUseDriver

# One scroll call moves at most one viewport height, which keeps each step reviewable.
MAX_SCROLL_PIXELS = 4096

# A page may update asynchronously after an action, so one immediate read can
# return the pre-action screen and record no transition. Poll until the screen id
# repeats twice, or until the deadline bounds the cost on a page that never settles.
SETTLE_QUIET_S = 0.15
SETTLE_DEADLINE_S = 4.0
# An action that changes nothing must not pay the whole deadline. A short grace
# window is enough to catch a slow no-op, and a change is still followed to its end.
SETTLE_UNCHANGED_S = 0.6

# A scroll transition carries this anchor id prefix plus its two pixel deltas.
# A scroll edge has no page anchor, so this id is the only thing that marks it.
SCROLL_ANCHOR_PREFIX = "scroll"
SCROLL_LABEL = "scroll the viewport"


def scroll_anchor(dx: float, dy: float) -> str:
    """Name a scroll edge by the deltas it applies."""
    return f"{SCROLL_ANCHOR_PREFIX}-{int(dx)}-{int(dy)}"


def scroll_deltas(anchor_id: str) -> tuple[float, float] | None:
    """Read the deltas back out of a scroll edge name, or None for a plain anchor."""
    match = re.fullmatch(rf"{SCROLL_ANCHOR_PREFIX}-(-?\d+)-(-?\d+)", anchor_id)
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))

# Keys a caller may send. Each one is refused unless it appears here.
ALLOWED_KEYS = frozenset({"enter", "escape"})


def _bounded_delta(raw: Any, name: str) -> float:
    """Validate one signed pixel delta for a scroll step."""
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number of pixels") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if abs(value) > MAX_SCROLL_PIXELS:
        raise ValueError(f"{name} must be between -{MAX_SCROLL_PIXELS} and {MAX_SCROLL_PIXELS} pixels")
    return value


def screen_id_at(raw: Mapping[str, Any]) -> str:
    """Derive the screen id, folding the scroll offset into it.

    Two positions in one scrolled page hold different content but the same
    visible anchors. Without the offset, a scrolled screen would answer to the
    id of the unscrolled one, and a stale-screen check would pass wrongly.
    The fragment cannot carry the offset, because a screen identity drops the
    query and fragment to avoid storing tokens.
    """
    base = ScreenState.create(raw).id
    scroll = raw.get("scroll")
    if not isinstance(scroll, Mapping):
        return base
    offset = [int(scroll.get("x", 0)), int(scroll.get("y", 0))]
    if offset == [0, 0]:
        return base
    identity = json.dumps([base, offset], separators=(",", ":"))
    return "s-" + hashlib.sha256(identity.encode()).hexdigest()[:20]


class PulseService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    @staticmethod
    def settled_observation(driver, app_id: str, expected: str,
                            *, screenshot_digest: bool = True) -> tuple[dict, str]:
        """Read the page until its screen id holds still, then return that read.

        An action on an async page changes the DOM after the call returns. One
        immediate read then sees the old screen and the transition goes
        unrecorded. Repeat reads until two agree, and stop at the deadline so a
        page that never settles still yields its last state. A page still on the
        expected screen gets a shorter grace, because an action that changed
        nothing should not cost the full wait.
        """
        import time
        started = time.monotonic()
        deadline = started + SETTLE_DEADLINE_S
        unchanged_by = started + SETTLE_UNCHANGED_S
        previous = None
        raw = driver.observe(app_id, screenshot_digest=False)
        while True:
            current = screen_id_at(raw)
            settled = current == previous and current != expected
            limit = deadline if current != expected else unchanged_by
            if settled or time.monotonic() >= limit:
                break
            previous = current
            time.sleep(SETTLE_QUIET_S)
            raw = driver.observe(app_id, screenshot_digest=False)
        if screenshot_digest:
            raw = driver.observe(app_id)
        return raw, screen_id_at(raw)

    def record_screen(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "")))
        screen_map = self.store.load_map(app_id) or ScreenMap.create(
            app_id, columns=int(args.get("columns", 8)), rows=int(args.get("rows", 12)))
        screen = screen_map.add_screen({**args, "id": screen_id_at(args)})
        self.store.save_map(screen_map)
        return {"app_id": app_id, "screen_id": screen.id,
                "anchor_count": len(screen.anchors),
                "grid": screen_map.grid(screen.id)}

    def record_transition(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "")))
        screen_map = self.store.load_map(app_id)
        if screen_map is None:
            raise KeyError(f"map not found for app: {app_id}")
        source_id = safe_id(str(args.get("source", "")))
        source = screen_map.screens.get(source_id)
        if source is None:
            raise KeyError(f"source screen not found: {source_id}")
        anchor_id = safe_id(str(args.get("anchor_id", "")))
        anchor = next((item for item in source.anchors if item.id == anchor_id), None)
        if anchor is None:
            raise KeyError(f"anchor not found on source screen: {anchor_id}")
        verified = args.get("verified")
        if not isinstance(verified, bool):
            raise ValueError("verified must be a boolean")
        edge = screen_map.add_transition({
            "source": source.id, "anchor_id": anchor.id, "target": args.get("target"),
            "label": anchor.label, "effect": anchor.effect,
            "verified": verified,
        })
        self.store.save_map(screen_map)
        return {"transition": edge.__dict__, "route_eligible": edge.verified}

    def get_map(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "")))
        screen_map = self.store.load_map(app_id)
        if screen_map is None:
            raise KeyError(f"map not found for app: {app_id}")
        requested = args.get("screen_id")
        if requested is None:
            return {
                "app_id": app_id,
                "grid": {"columns": screen_map.columns, "rows": screen_map.rows},
                "screens": [{"id": screen.id, "url": screen.url, "title": screen.title,
                             "anchor_count": len(screen.anchors)}
                            for screen in screen_map.screens.values()],
                "transitions": [edge.__dict__ for edge in screen_map.transitions],
            }
        screen_id = safe_id(str(requested))
        screen = screen_map.screens.get(screen_id)
        if screen is None:
            raise KeyError(f"screen not found: {screen_id}")
        return {"screen": screen.to_dict(), "grid": screen_map.grid(screen_id),
                "grid_size": {"columns": screen_map.columns, "rows": screen_map.rows}}

    def route(self, args: Mapping[str, Any]) -> dict[str, Any] | None:
        app_id = safe_id(str(args.get("app_id", "")))
        screen_map = self.store.load_map(app_id)
        if screen_map is None:
            raise KeyError(f"map not found for app: {app_id}")
        route = screen_map.route(str(args.get("start", "")), str(args.get("target", "")))
        return {"found": route is not None, "route": route}

    def save_routine(self, args: Mapping[str, Any]) -> dict[str, Any]:
        routine = self.store.save_routine(args)
        return routine.to_dict()

    def list_routines(self, args: Mapping[str, Any]) -> list[dict[str, Any]]:
        app_id = args.get("app_id")
        return self.store.list_routines(safe_id(str(app_id)) if app_id else None)

    def get_routine(self, args: Mapping[str, Any]) -> dict[str, Any]:
        routine_id = safe_id(str(args.get("routine_id", "")))
        routine = self.store.load_routine(routine_id)
        if routine is None:
            raise KeyError(f"routine not found: {routine_id}")
        return routine

    def browser_observe(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "browser")))
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        driver = BrowserDriver(port, target_url=page_url)
        try:
            observation = driver.observe(app_id)
        finally:
            driver.close()
        recorded = self.record_screen(observation)
        return {"screen_id": recorded["screen_id"], "url": observation["url"],
                "title": observation["title"], "viewport": observation["viewport"],
                "anchor_count": recorded["anchor_count"], "grid": recorded["grid"],
                "anchors": observation["anchors"], "screenshot_sha256": observation["screenshot_sha256"]}

    def browser_targets(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """List the page tabs one CDP port serves, in the order a call would choose.

        One port can hold several pages. A caller that names a target_url gets the
        page it means, and this list shows the choice it made possible.
        """
        from .drivers.cdp import page_targets
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        pages = page_targets(port, page_url)
        return {"port": port, "chosen": pages[0].get("url", ""),
                "pages": [{"url": page.get("url", ""), "title": page.get("title", "")}
                          for page in pages]}

    def browser_click(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "browser")))
        expected = safe_id(str(args.get("expected_screen", "")))
        anchor_id = safe_id(str(args.get("anchor_id", "")))
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        authorized = args.get("authorized_effects", [])
        if not isinstance(authorized, list) or any(x not in {"write", "irreversible"} for x in authorized):
            raise ValueError("authorized_effects may contain only write or irreversible")
        screen_map = self.store.load_map(app_id)
        if screen_map is None or expected not in screen_map.screens:
            raise KeyError("expected screen is not in the stored map")
        before = screen_map.screens[expected]
        anchor = next((a for a in before.anchors if a.id == anchor_id), None)
        if anchor is None or not anchor.actionable:
            raise ValueError("anchor is not an actionable control on the expected screen")
        if anchor.effect != "read" and anchor.effect not in authorized:
            raise PermissionError(f"clicking this {anchor.effect} control requires explicit authorization")
        driver = BrowserDriver(port, target_url=page_url)
        try:
            current = screen_id_at(driver.observe(app_id))
            if current != expected:
                raise ValueError(f"stale map: expected screen {expected}, observed {current}; observe and replan")
            center_x = (anchor.bounds.x + anchor.bounds.width / 2) * before.viewport["width"]
            center_y = (anchor.bounds.y + anchor.bounds.height / 2) * before.viewport["height"]
            driver.click(center_x, center_y)
            after_raw, after_id = self.settled_observation(driver, app_id, expected)
        finally:
            driver.close()
        saved = self.record_screen(after_raw)
        after_id = saved["screen_id"]
        changed = after_id != expected
        edge_result = None
        if changed:
            edge_result = self.record_transition({"app_id": app_id, "source": expected,
                "anchor_id": anchor_id, "target": after_id, "verified": True})["transition"]
        return {"clicked": True, "from_screen": expected, "to_screen": after_id,
                "state_changed": changed, "transition": edge_result,
                "observed_title": after_raw["title"], "observed_url": after_raw["url"]}

    def browser_fill(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Type a value into one mapped field. The value is not stored or returned."""
        app_id = safe_id(str(args.get("app_id", "browser")))
        expected = safe_id(str(args.get("expected_screen", "")))
        anchor_id = safe_id(str(args.get("anchor_id", "")))
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        authorized = args.get("authorized_effects", [])
        if not isinstance(authorized, list) or any(x not in {"write", "irreversible"} for x in authorized):
            raise ValueError("authorized_effects may contain only write or irreversible")
        if "write" not in authorized:
            raise PermissionError("filling a field requires explicit authorization: [\"write\"]")
        value = args.get("value")
        if not isinstance(value, str) or not value:
            raise ValueError("value must be a non-empty string")
        screen_map = self.store.load_map(app_id)
        if screen_map is None or expected not in screen_map.screens:
            raise KeyError("expected screen is not in the stored map")
        before = screen_map.screens[expected]
        anchor = next((a for a in before.anchors if a.id == anchor_id), None)
        if anchor is None or not anchor.actionable:
            raise ValueError("anchor is not an actionable control on the expected screen")
        if anchor.role not in {"input", "textbox", "combobox"}:
            raise ValueError(f"anchor role {anchor.role} is not a fillable field")
        if anchor.effect != "read" and anchor.effect not in authorized:
            raise PermissionError(f"filling this {anchor.effect} control requires explicit authorization")
        x = (anchor.bounds.x + anchor.bounds.width / 2) * before.viewport["width"]
        y = (anchor.bounds.y + anchor.bounds.height / 2) * before.viewport["height"]
        driver = BrowserDriver(port, target_url=page_url)
        keep_focus = bool(args.get("keep_focus"))
        try:
            current = screen_id_at(driver.observe(app_id, screenshot_digest=False))
            if current != expected:
                raise ValueError(f"stale map: expected screen {expected}, observed {current}; observe and replan")
            rejection = field_rejection(driver.inspect_field(x, y))
            if rejection is not None:
                raise ValueError(FIELD_REJECTION_MESSAGES.get(rejection, FIELD_REJECTION_MESSAGES["unsupported"]))
            if not driver.focus_field(x, y):
                raise ValueError(FIELD_REJECTION_MESSAGES["focus_refused"])
            entry = driver.entry_text(value)
            if not entry:
                raise ValueError("value is empty once line breaks are trimmed for a single-line field")
            driver.insert_text(entry)
            confirmation = driver.confirm_entry(len(entry))
            if not confirmation["filled"]:
                if not confirmation["found"]:
                    raise ValueError(FIELD_REJECTION_MESSAGES["focus_lost"])
                raise ValueError(FIELD_REJECTION_MESSAGES["fill_failed"])
            # An exact read-back catches a page that rewrites or truncates the
            # entry. Only a rejection code leaves this call, never the text.
            problem = driver.entry_problem(entry)
            if problem is not None:
                raise ValueError(FIELD_REJECTION_MESSAGES[problem])
            if keep_focus:
                # A key sent next needs this focus, so the page keeps it.
                summary = {"blurred": False}
            else:
                # A focused field's text appears in the next observation's anchor
                # labels. Forgetting focus keeps the value out of the map.
                driver.blur_field()
                summary = {"blurred": True}
            # A live filter or counter can change the screen after a fill, so the
            # read settles first. Only the final digest-bearing read leaves here.
            self.settled_observation(driver, app_id, expected, screenshot_digest=False)
            after_raw = redact(driver.observe(app_id), value)
            after_raw = redact(redact(after_raw, entry), value)
        finally:
            driver.close()
        saved = self.record_screen(after_raw)
        after_id = saved["screen_id"]
        return {"filled": True, "field": anchor_id, "value_length": len(entry),
                "from_screen": expected, "to_screen": after_id,
                "state_changed": after_id != expected, "submitted": False,
                "blurred": summary["blurred"],
                "observed_title": after_raw["title"], "observed_url": after_raw["url"]}

    def browser_scroll(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Scroll the current browser viewport by a bounded pixel delta."""
        app_id = safe_id(str(args.get("app_id", "browser")))
        expected = safe_id(str(args.get("expected_screen", "")))
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        dx = _bounded_delta(args.get("dx", 0), "dx")
        dy = _bounded_delta(args.get("dy", 0), "dy")
        if dx == 0 and dy == 0:
            raise ValueError("scroll requires a non-zero dx or dy")
        screen_map = self.store.load_map(app_id)
        if screen_map is None or expected not in screen_map.screens:
            raise KeyError("expected screen is not in the stored map")
        before = screen_map.screens[expected]
        driver = BrowserDriver(port, target_url=page_url)
        try:
            current = screen_id_at(driver.observe(app_id, screenshot_digest=False))
            if current != expected:
                raise ValueError(f"stale map: expected screen {expected}, observed {current}; observe and replan")
            offsets = driver.scroll_by(dx, dy)
            # The offset is the state a scroll changes, so the settled read must
            # carry the final offset rather than an intermediate one.
            after_raw, after_id = self.settled_observation(driver, app_id, expected)
            after_raw = {**after_raw, "scroll": offsets.get("after", after_raw.get("scroll"))}
            after_id = screen_id_at(after_raw)
        finally:
            driver.close()
        saved = self.record_screen(after_raw)
        after_id = saved["screen_id"]
        before_offset = offsets.get("before", {})
        after_offset = offsets.get("after", {})
        changed = after_id != expected
        if changed:
            # A scroll is a verified move, so it can join a route. Its anchor id
            # encodes the deltas, which is all a replay needs to repeat it.
            edge = {"source": expected, "anchor_id": scroll_anchor(dx, dy),
                    "target": after_id, "label": SCROLL_LABEL,
                    "effect": "write", "verified": True}
            current_map = self.store.load_map(app_id)
            if current_map is not None and expected in current_map.screens:
                scrolled = Transition.create(edge)
                if scrolled not in current_map.transitions:
                    current_map.transitions.append(scrolled)
                    self.store.save_map(current_map)
        return {"scrolled": True, "dx": dx, "dy": dy,
                "offset_before": before_offset, "offset_after": after_offset,
                "moved": {"x": after_offset.get("x", 0) - before_offset.get("x", 0),
                          "y": after_offset.get("y", 0) - before_offset.get("y", 0)},
                "from_screen": expected, "to_screen": after_id,
                "state_changed": changed, "grid": saved["grid"],
                "anchors": after_raw["anchors"], "observed_title": after_raw["title"],
                "observed_url": after_raw["url"]}

    def browser_key(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Send one allowlisted key to the focused element on the expected screen."""
        app_id = safe_id(str(args.get("app_id", "browser")))
        expected = safe_id(str(args.get("expected_screen", "")))
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        authorized = args.get("authorized_effects", [])
        if not isinstance(authorized, list) or any(x not in {"write", "irreversible"} for x in authorized):
            raise ValueError("authorized_effects may contain only write or irreversible")
        name = str(args.get("key", "")).strip().lower()
        if name not in ALLOWED_KEYS:
            raise ValueError(f"key must be one of {sorted(ALLOWED_KEYS)}")
        if "write" not in authorized:
            raise PermissionError("sending a key requires explicit authorization: [\"write\"]")
        screen_map = self.store.load_map(app_id)
        if screen_map is None or expected not in screen_map.screens:
            raise KeyError("expected screen is not in the stored map")
        driver = BrowserDriver(port, target_url=page_url)
        try:
            current = screen_id_at(driver.observe(app_id, screenshot_digest=False))
            if current != expected:
                raise ValueError(f"stale map: expected screen {expected}, observed {current}; observe and replan")
            focus = driver.focused_tag()
            driver.press_key(name)
            after_raw, after_id = self.settled_observation(driver, app_id, expected)
        finally:
            driver.close()
        saved = self.record_screen(after_raw)
        after_id = saved["screen_id"]
        focused = focus in {"input", "textarea", "select"} or focus == ""
        return {"sent": name, "focused_element": focus, "focus_was_editable": focused,
                "from_screen": expected, "to_screen": after_id,
                "state_changed": after_id != expected,
                "observed_title": after_raw["title"], "observed_url": after_raw["url"]}

    def browser_replay(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Replay a learned route in one call; stop immediately on divergence."""
        app_id = safe_id(str(args.get("app_id", "browser")))
        start = safe_id(str(args.get("start", "")))
        target = str(args.get("target", "")).strip()
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
        page_url = str(args.get("target_url", "")).strip()
        authorized = args.get("authorized_effects", [])
        if not isinstance(authorized, list) or any(x not in {"write", "irreversible"} for x in authorized):
            raise ValueError("authorized_effects may contain only write or irreversible")
        screen_map = self.store.load_map(app_id)
        if screen_map is None:
            raise KeyError(f"map not found for app: {app_id}")
        plan = screen_map.route(start, target)
        if plan is None:
            raise ValueError("no route of verified transitions exists for this target")
        for edge in plan["steps"]:
            source = screen_map.screens[edge["source"]]
            deltas = scroll_deltas(edge["anchor_id"])
            if deltas is not None:
                continue
            anchor = next((a for a in source.anchors if a.id == edge["anchor_id"]), None)
            if anchor is None:
                raise ValueError("mapped route anchor disappeared")
            if anchor.effect != "read" and anchor.effect not in authorized:
                raise PermissionError(f"route includes {anchor.effect} action; explicit authorization required")
        driver = BrowserDriver(port, target_url=page_url)
        completed = []
        final = None
        try:
            start_id = screen_id_at(driver.observe(app_id, screenshot_digest=False))
            if start_id != start:
                return {"completed": False, "start_expected": start, "start_observed": start_id,
                        "steps_completed": 0, "reason": "stale start screen; observe and replan"}
            for index, edge in enumerate(plan["steps"]):
                current_map = self.store.load_map(app_id)
                source = current_map.screens.get(edge["source"]) if current_map else None
                anchor = next((a for a in source.anchors if a.id == edge["anchor_id"]), None) if source else None
                if anchor is None:
                    deltas = scroll_deltas(edge["anchor_id"])
                    if deltas is None:
                        return {"completed": False, "steps_completed": len(completed),
                                "steps": completed, "reason": "mapped route anchor disappeared"}
                    driver.scroll_by(*deltas)
                else:
                    x = (anchor.bounds.x + anchor.bounds.width / 2) * source.viewport["width"]
                    y = (anchor.bounds.y + anchor.bounds.height / 2) * source.viewport["height"]
                    driver.click(x, y)
                is_last = index == len(plan["steps"]) - 1
                # A step on an async page lands after the click returns, so the
                # check reads the settled screen. An unsettled read reports a
                # divergence that a second look would clear.
                raw, observed = self.settled_observation(
                    driver, app_id, edge["source"], screenshot_digest=is_last)
                if observed != edge["target"]:
                    raw["screenshot_sha256"] = driver.observe(app_id, screenshot_digest=True)["screenshot_sha256"]
                    self.record_screen(raw)
                    return {"completed": False, "steps_completed": len(completed),
                            "steps": completed, "expected_screen": edge["target"],
                            "observed_screen": observed,
                            "reason": "screen diverged; route stopped for replanning"}
                completed.append({"from": edge["source"], "anchor_id": edge["anchor_id"],
                                  "to": observed, "verified": True})
                if is_last:
                    self.record_screen(raw)
                    # The last settled read is the final state. Returning it saves
                    # the caller the confirmation observe, which is a whole model
                    # turn on every route.
                    final = {"screen_id": observed, "title": raw.get("title", ""),
                             "viewport": raw.get("viewport"),
                             "anchor_count": len(raw.get("anchors", [])),
                             "screenshot_sha256": raw.get("screenshot_sha256"),
                             "anchors": raw.get("anchors", [])}
            result = {"completed": True, "target_screen": plan["target"],
                      "steps_completed": len(completed), "steps": completed}
            # A route with no steps already sits on the target, so it has no read
            # to report. Only a route that acted carries a final state.
            if final is not None:
                result.update(final)
            return result
        finally:
            driver.close()

    def desktop_observe(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "desktop")))
        application = str(args.get("application", "")).strip() or None
        driver = ComputerUseDriver()
        try:
            observation = driver.observe(app_id, application=application)
        finally:
            driver.close()
        recorded = self.record_screen(observation)
        return {"screen_id":recorded["screen_id"], "title":observation["title"],
                "viewport":observation["viewport"], "anchor_count":recorded["anchor_count"],
                "grid":recorded["grid"], "anchors":observation["anchors"],
                "screenshot_sha256":observation["screenshot_sha256"]}

    def desktop_click(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "desktop")))
        expected = safe_id(str(args.get("expected_screen", "")))
        anchor_id = safe_id(str(args.get("anchor_id", "")))
        application = str(args.get("application", "")).strip() or None
        authorized = args.get("authorized_effects", [])
        if not isinstance(authorized, list) or any(x not in {"write", "irreversible"} for x in authorized):
            raise ValueError("authorized_effects may contain only write or irreversible")
        screen_map = self.store.load_map(app_id)
        if screen_map is None or expected not in screen_map.screens:
            raise KeyError("expected desktop screen is not in the stored map")
        source = screen_map.screens[expected]
        anchor = next((a for a in source.anchors if a.id == anchor_id), None)
        if anchor is None or not anchor.actionable:
            raise ValueError("anchor is not actionable on the expected desktop screen")
        if anchor.effect != "read" and anchor.effect not in authorized:
            raise PermissionError(f"clicking this {anchor.effect} control requires explicit authorization")
        driver = ComputerUseDriver()
        try:
            needs_screenshot = any(item.source == "vision" for item in source.anchors)
            current = ScreenState.create(driver.observe(app_id, screenshot=needs_screenshot,
                                                        application=application, map_hint=source))
            if current.id != expected:
                raise ValueError(f"stale desktop map: expected {expected}, observed {current.id}; observe and replan")
            x = (anchor.bounds.x + anchor.bounds.width / 2) * source.viewport["width"]
            y = (anchor.bounds.y + anchor.bounds.height / 2) * source.viewport["height"]
            click_result = driver.click(x, y)
            after_raw = driver.observe(app_id, application=application)
        finally:
            driver.close()
        saved = self.record_screen(after_raw)
        target = saved["screen_id"]
        changed = target != expected
        edge = None
        if changed:
            edge = self.record_transition({"app_id":app_id, "source":expected,
                "anchor_id":anchor_id, "target":target, "verified":True})["transition"]
        return {"clicked":bool(click_result.get("ok")), "from_screen":expected,
                "to_screen":target, "state_changed":changed, "transition":edge,
                "message":click_result.get("message", "")}

    def desktop_replay(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "desktop")))
        start = safe_id(str(args.get("start", "")))
        target = str(args.get("target", "")).strip()
        application = str(args.get("application", "")).strip() or None
        authorized = args.get("authorized_effects", [])
        if not isinstance(authorized, list) or any(x not in {"write", "irreversible"} for x in authorized):
            raise ValueError("authorized_effects may contain only write or irreversible")
        screen_map = self.store.load_map(app_id)
        if screen_map is None:
            raise KeyError(f"map not found for app: {app_id}")
        plan = screen_map.route(start, target)
        if plan is None:
            raise ValueError("no route of verified desktop transitions exists for this target")
        for edge in plan["steps"]:
            anchor = next((a for a in screen_map.screens[edge["source"]].anchors
                           if a.id == edge["anchor_id"]), None)
            if anchor is None:
                raise ValueError("mapped desktop route anchor disappeared")
            if anchor.effect != "read" and anchor.effect not in authorized:
                raise PermissionError(f"route includes {anchor.effect} action; explicit authorization required")
        driver = ComputerUseDriver()
        completed = []
        try:
            start_screen = screen_map.screens[start]
            start_needs_screenshot = any(item.source == "vision" for item in start_screen.anchors)
            raw = driver.observe(app_id, screenshot=start_needs_screenshot,
                                 application=application, map_hint=start_screen)
            current = ScreenState.create(raw)
            if current.id != start:
                return {"completed":False, "start_expected":start, "start_observed":current.id,
                        "steps_completed":0, "reason":"stale start screen; observe and replan"}
            for index, edge in enumerate(plan["steps"]):
                source = screen_map.screens[edge["source"]]
                anchor = next(a for a in source.anchors if a.id == edge["anchor_id"])
                x = (anchor.bounds.x + anchor.bounds.width / 2) * source.viewport["width"]
                y = (anchor.bounds.y + anchor.bounds.height / 2) * source.viewport["height"]
                click_result = driver.click(x, y)
                if not click_result.get("ok"):
                    return {"completed":False, "steps_completed":len(completed),
                            "steps":completed, "reason":click_result.get("message", "desktop click failed")}
                target_screen = screen_map.screens[edge["target"]]
                needs_screenshot = any(item.source == "vision" for item in target_screen.anchors)
                raw = driver.observe(app_id, screenshot=needs_screenshot, application=application,
                                     map_hint=target_screen)
                observed = ScreenState.create(raw)
                if observed.id != edge["target"]:
                    raw = driver.observe(app_id, screenshot=True, application=application)
                    observed = ScreenState.create(raw)
                    self.record_screen(raw)
                    return {"completed":False, "steps_completed":len(completed),
                            "steps":completed, "expected_screen":edge["target"],
                            "observed_screen":observed.id,
                            "reason":"desktop state diverged; route stopped for replanning"}
                completed.append({"from":edge["source"], "anchor_id":edge["anchor_id"],
                                  "to":observed.id, "verified":True})
                if needs_screenshot:
                    self.record_screen(raw)
            return {"completed":True, "target_screen":plan["target"],
                    "steps_completed":len(completed), "steps":completed}
        finally:
            driver.close()
