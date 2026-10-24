"""Application operations used by the MCP transport."""
from __future__ import annotations

import os
from typing import Any, Mapping

from .contracts import ScreenState, safe_id
from .screen_map import ScreenMap
from .store import Store
from .drivers.browser import BrowserDriver
from .drivers.computer_use import ComputerUseDriver


class PulseService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def record_screen(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "")))
        screen_map = self.store.load_map(app_id) or ScreenMap.create(
            app_id, columns=int(args.get("columns", 8)), rows=int(args.get("rows", 12)))
        screen = screen_map.add_screen(args)
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
        driver = BrowserDriver(port)
        try:
            observation = driver.observe(app_id)
        finally:
            driver.close()
        recorded = self.record_screen(observation)
        return {"screen_id": recorded["screen_id"], "url": observation["url"],
                "title": observation["title"], "viewport": observation["viewport"],
                "anchor_count": recorded["anchor_count"], "grid": recorded["grid"],
                "anchors": observation["anchors"], "screenshot_sha256": observation["screenshot_sha256"]}

    def browser_click(self, args: Mapping[str, Any]) -> dict[str, Any]:
        app_id = safe_id(str(args.get("app_id", "browser")))
        expected = safe_id(str(args.get("expected_screen", "")))
        anchor_id = safe_id(str(args.get("anchor_id", "")))
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
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
        driver = BrowserDriver(port)
        try:
            current_raw = driver.observe(app_id)
            from .contracts import ScreenState
            current = ScreenState.create(current_raw)
            if current.id != expected:
                raise ValueError(f"stale map: expected screen {expected}, observed {current.id}; observe and replan")
            center_x = (anchor.bounds.x + anchor.bounds.width / 2) * before.viewport["width"]
            center_y = (anchor.bounds.y + anchor.bounds.height / 2) * before.viewport["height"]
            driver.click(center_x, center_y)
            after_raw = driver.observe(app_id)
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

    def browser_replay(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Replay a learned route in one call; stop immediately on divergence."""
        app_id = safe_id(str(args.get("app_id", "browser")))
        start = safe_id(str(args.get("start", "")))
        target = str(args.get("target", "")).strip()
        port = int(args.get("port", os.environ.get("PULSE_CDP_PORT", "9222")))
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
            anchor = next((a for a in source.anchors if a.id == edge["anchor_id"]), None)
            if anchor is None:
                raise ValueError("mapped route anchor disappeared")
            if anchor.effect != "read" and anchor.effect not in authorized:
                raise PermissionError(f"route includes {anchor.effect} action; explicit authorization required")
        from .contracts import ScreenState
        driver = BrowserDriver(port)
        completed = []
        try:
            raw = driver.observe(app_id, screenshot_digest=False)
            current = ScreenState.create(raw)
            if current.id != start:
                return {"completed": False, "start_expected": start, "start_observed": current.id,
                        "steps_completed": 0, "reason": "stale start screen; observe and replan"}
            for index, edge in enumerate(plan["steps"]):
                current_map = self.store.load_map(app_id)
                source = current_map.screens.get(edge["source"]) if current_map else None
                anchor = next((a for a in source.anchors if a.id == edge["anchor_id"]), None) if source else None
                if anchor is None:
                    return {"completed": False, "steps_completed": len(completed),
                            "steps": completed, "reason": "mapped route anchor disappeared"}
                x = (anchor.bounds.x + anchor.bounds.width / 2) * source.viewport["width"]
                y = (anchor.bounds.y + anchor.bounds.height / 2) * source.viewport["height"]
                driver.click(x, y)
                is_last = index == len(plan["steps"]) - 1
                raw = driver.observe(app_id, screenshot_digest=is_last)
                observed = ScreenState.create(raw)
                if observed.id != edge["target"]:
                    raw["screenshot_sha256"] = driver.observe(app_id, screenshot_digest=True)["screenshot_sha256"]
                    self.record_screen(raw)
                    return {"completed": False, "steps_completed": len(completed),
                            "steps": completed, "expected_screen": edge["target"],
                            "observed_screen": observed.id,
                            "reason": "screen diverged; route stopped for replanning"}
                completed.append({"from": edge["source"], "anchor_id": edge["anchor_id"],
                                  "to": observed.id, "verified": True})
                if is_last:
                    self.record_screen(raw)
            return {"completed": True, "target_screen": plan["target"],
                    "steps_completed": len(completed), "steps": completed}
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
