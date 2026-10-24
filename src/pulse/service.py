"""Application operations used by the MCP transport."""
from __future__ import annotations

from typing import Any, Mapping

from .contracts import safe_id
from .screen_map import ScreenMap
from .store import Store


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
