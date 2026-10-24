"""Screen graph and grid operations. All coordinates are normalized fractions."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .contracts import ScreenState, Transition, safe_id


@dataclass
class ScreenMap:
    app_id: str
    columns: int = 8
    rows: int = 12
    schema_version: int = 1
    screens: dict[str, ScreenState] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)

    @classmethod
    def create(cls, app_id: str, *, columns: int = 8, rows: int = 12) -> "ScreenMap":
        app_id = safe_id(app_id)
        if not 1 <= columns <= 64 or not 1 <= rows <= 64:
            raise ValueError("grid columns and rows must be between 1 and 64")
        return cls(app_id, columns, rows)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScreenMap":
        result = cls.create(str(raw.get("app_id", "")), columns=int(raw.get("columns", 8)),
                            rows=int(raw.get("rows", 12)))
        result.schema_version = int(raw.get("schema_version", 1))
        if result.schema_version != 1:
            raise ValueError(f"unsupported screen map version: {result.schema_version}")
        for item in raw.get("screens", ()):
            screen = ScreenState.from_dict(item)
            if screen.app_id != result.app_id:
                raise ValueError("screen app_id does not match map app_id")
            result.screens[screen.id] = screen
        result.transitions = [Transition.create(x) for x in raw.get("transitions", ())]
        for edge in result.transitions:
            result._validate_edge(edge)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "app_id": self.app_id,
            "columns": self.columns,
            "rows": self.rows,
            "screens": [self.screens[key].to_dict() for key in sorted(self.screens)],
            "transitions": [asdict(edge) for edge in self.transitions],
        }

    def add_screen(self, raw: Mapping[str, Any]) -> ScreenState:
        screen = ScreenState.create({**raw, "app_id": self.app_id})
        self.screens[screen.id] = screen
        return screen

    def add_transition(self, raw: Mapping[str, Any]) -> Transition:
        edge = Transition.create(raw)
        self._validate_edge(edge)
        if edge not in self.transitions:
            self.transitions.append(edge)
        return edge

    def _validate_edge(self, edge: Transition) -> None:
        source = self.screens.get(edge.source)
        if source is None or edge.target not in self.screens:
            raise ValueError("transition source and target must already exist in the map")
        anchor = next((item for item in source.anchors if item.id == edge.anchor_id), None)
        if anchor is None or not anchor.actionable:
            raise ValueError("transition anchor must be actionable on its source screen")
        if anchor.label.casefold() != edge.label.casefold():
            raise ValueError("transition label must match its source anchor")
        if anchor.effect != edge.effect:
            raise ValueError("transition effect must match its source anchor")

    def grid(self, screen_id: str) -> list[list[list[dict[str, Any]]]]:
        screen = self.screens.get(safe_id(screen_id))
        if screen is None:
            raise KeyError(f"screen not found: {screen_id}")
        cells: list[list[list[dict[str, Any]]]] = [
            [[] for _ in range(self.columns)] for _ in range(self.rows)
        ]
        for anchor in screen.anchors:
            col = min(self.columns - 1, int((anchor.bounds.x + anchor.bounds.width / 2) * self.columns))
            row = min(self.rows - 1, int((anchor.bounds.y + anchor.bounds.height / 2) * self.rows))
            cells[row][col].append({"id": anchor.id, "role": anchor.role, "label": anchor.label,
                                    "actionable": anchor.actionable, "effect": anchor.effect,
                                    "confidence": anchor.confidence})
        return cells

    def route(self, start: str, target: str) -> dict[str, Any] | None:
        """Return the shortest verified transition path to a screen or visible anchor label."""
        start = safe_id(start)
        if start not in self.screens:
            raise KeyError(f"start screen not found: {start}")
        target_folded = " ".join(target.split()).casefold()
        if not target_folded:
            raise ValueError("target cannot be empty")

        def matches(screen: ScreenState) -> bool:
            return (screen.id == target or screen.title.casefold() == target_folded
                    or any(a.label.casefold() == target_folded for a in screen.anchors))

        queue: deque[tuple[str, list[Transition]]] = deque([(start, [])])
        seen = {start}
        while queue:
            screen_id, path = queue.popleft()
            screen = self.screens[screen_id]
            if matches(screen):
                return {"start": start, "target": screen_id,
                        "steps": [asdict(edge) for edge in path], "transition_count": len(path)}
            for edge in self.transitions:
                if edge.source == screen_id and edge.verified and edge.target not in seen:
                    seen.add(edge.target)
                    queue.append((edge.target, path + [edge]))
        return None
