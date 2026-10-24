"""Validated, transport-neutral contracts for screen maps and routines."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

_SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")


def safe_id(value: str) -> str:
    value = value.strip()
    if not _SLUG.fullmatch(value) or value in {".", ".."}:
        raise ValueError("id must be 1-80 letters, digits, dots, underscores or hyphens")
    return value


@dataclass(frozen=True)
class Bounds:
    """Normalized screen rectangle; coordinates are fractions of the viewport."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def create(cls, raw: Mapping[str, Any]) -> "Bounds":
        try:
            vals = tuple(float(raw[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("bounds require numeric x, y, width and height") from exc
        x, y, w, h = vals
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("bounds must be finite")
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            raise ValueError("bounds must be a positive rectangle inside the normalized viewport")
        return cls(x, y, w, h)

    @classmethod
    def from_pixels(cls, raw: Mapping[str, Any], viewport: Mapping[str, Any]) -> "Bounds":
        vw, vh = float(viewport["width"]), float(viewport["height"])
        if vw <= 0 or vh <= 0:
            raise ValueError("viewport dimensions must be positive")
        px, py = float(raw["x"]), float(raw["y"])
        pw, ph = float(raw["width"]), float(raw["height"])
        x, y = max(0.0, px), max(0.0, py)
        right, bottom = min(vw, px + pw), min(vh, py + ph)
        return cls.create({"x": x / vw, "y": y / vh,
                           "width": (right - x) / vw, "height": (bottom - y) / vh})


@dataclass(frozen=True)
class Anchor:
    """One actionable or informative item found by an accessibility/DOM/vision driver."""

    id: str
    role: str
    label: str
    bounds: Bounds
    source: str = "accessibility"
    actionable: bool = False
    effect: str = "read"
    selected: bool = False
    confidence: float = 1.0

    @classmethod
    def create(cls, raw: Mapping[str, Any]) -> "Anchor":
        anchor_id = safe_id(str(raw.get("id", "")))
        role = str(raw.get("role", "unknown")).strip()[:64] or "unknown"
        label = " ".join(str(raw.get("label", "")).split())[:240]
        if not label:
            raise ValueError("anchor label cannot be empty")
        source = str(raw.get("source", "accessibility"))
        if source not in {"accessibility", "dom", "vision", "manual"}:
            raise ValueError(f"unsupported anchor source: {source}")
        effect = str(raw.get("effect", "read"))
        if effect not in {"read", "write", "irreversible"}:
            raise ValueError("effect must be read, write or irreversible")
        confidence = float(raw.get("confidence", 1.0))
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        actionable = raw.get("actionable", False)
        selected = raw.get("selected", False)
        if not isinstance(actionable, bool) or not isinstance(selected, bool):
            raise ValueError("actionable and selected must be booleans")
        return cls(anchor_id, role, label, Bounds.create(raw.get("bounds", {})), source,
                   actionable, effect, selected, confidence)


@dataclass(frozen=True)
class ScreenState:
    id: str
    app_id: str
    url: str
    title: str
    viewport: Mapping[str, int]
    anchors: tuple[Anchor, ...]
    screenshot_sha256: str | None = None
    observed_at: float = field(default_factory=time.time)

    @classmethod
    def create(cls, raw: Mapping[str, Any]) -> "ScreenState":
        app_id = safe_id(str(raw.get("app_id", "")))
        url = str(raw.get("url", ""))[:2048]
        if url:
            parts = urlsplit(url)
            # Search parameters and fragments often carry auth tokens or task ids.
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        title = " ".join(str(raw.get("title", "")).split())[:240]
        viewport_raw = raw.get("viewport", {})
        try:
            width, height = int(viewport_raw["width"]), int(viewport_raw["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("viewport requires integer width and height") from exc
        if width < 1 or height < 1 or width > 32768 or height > 32768:
            raise ValueError("viewport dimensions must be between 1 and 32768")
        anchors = tuple(Anchor.create(item) for item in raw.get("anchors", ()))
        if len({item.id for item in anchors}) != len(anchors):
            raise ValueError("anchor ids must be unique within a screen")
        landmarks = sorted((a.role.lower(), a.label.casefold(), a.selected,
                            round(a.bounds.x, 2), round(a.bounds.y, 2),
                            round(a.bounds.width, 2), round(a.bounds.height, 2)) for a in anchors)
        identity = json.dumps([app_id, url, title, landmarks], ensure_ascii=False, separators=(",", ":"))
        state_id = str(raw.get("id") or "s-" + hashlib.sha256(identity.encode()).hexdigest()[:20])
        safe_id(state_id)
        digest = raw.get("screenshot_sha256")
        if digest is not None and not re.fullmatch(r"[a-f0-9]{64}", str(digest)):
            raise ValueError("screenshot_sha256 must be a lowercase SHA-256 digest")
        observed_at = float(raw.get("observed_at", time.time()))
        if not math.isfinite(observed_at) or observed_at <= 0:
            raise ValueError("observed_at must be a positive timestamp")
        return cls(state_id, app_id, url, title, {"width": width, "height": height},
                   anchors, str(digest) if digest else None, observed_at)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScreenState":
        prepared = dict(raw)
        prepared["anchors"] = [dict(a, bounds=dict(a["bounds"])) for a in raw.get("anchors", ())]
        return cls.create(prepared)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Transition:
    source: str
    anchor_id: str
    target: str
    label: str
    effect: str = "read"
    verified: bool = False

    @classmethod
    def create(cls, raw: Mapping[str, Any]) -> "Transition":
        source, anchor_id, target = (safe_id(str(raw.get(k, ""))) for k in ("source", "anchor_id", "target"))
        label = " ".join(str(raw.get("label", "")).split())[:240]
        if not label:
            raise ValueError("transition label cannot be empty")
        effect = str(raw.get("effect", "read"))
        if effect not in {"read", "write", "irreversible"}:
            raise ValueError("effect must be read, write or irreversible")
        verified = raw.get("verified", False)
        if not isinstance(verified, bool):
            raise ValueError("verified must be a boolean")
        return cls(source, anchor_id, target, label, effect, verified)


@dataclass(frozen=True)
class Routine:
    id: str
    app_id: str
    name: str
    steps: tuple[Mapping[str, Any], ...]
    final_state: str
    evidence: str
    status: str = "candidate"
    version: int = 1
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(cls, raw: Mapping[str, Any]) -> "Routine":
        routine_id = safe_id(str(raw.get("id", "")))
        app_id = safe_id(str(raw.get("app_id", "")))
        name = " ".join(str(raw.get("name", "")).split())[:120]
        steps_raw = raw.get("steps", ())
        if not name or not isinstance(steps_raw, (list, tuple)) or not steps_raw:
            raise ValueError("routine requires a name and at least one step")
        if len(steps_raw) > 100:
            raise ValueError("routine may contain at most 100 steps")
        steps = []
        for step in steps_raw:
            if not isinstance(step, Mapping):
                raise ValueError("routine steps must be objects")
            item = dict(step)
            allowed = {"anchor_id", "operation", "expected_state", "effect", "input_ref",
                       "precondition", "postcondition"}
            if set(item) - allowed:
                raise ValueError("routine steps may not store literal values or unknown fields")
            if not item.get("anchor_id") or not item.get("operation") or not item.get("expected_state"):
                raise ValueError("each routine step needs anchor_id, operation and expected_state")
            item["anchor_id"] = safe_id(str(item["anchor_id"]))
            for field_name in ("operation", "expected_state", "input_ref", "precondition", "postcondition"):
                if field_name in item:
                    item[field_name] = " ".join(str(item[field_name]).split())[:500]
            if item.get("input_ref"):
                item["input_ref"] = safe_id(item["input_ref"])
            item["effect"] = str(item.get("effect", "read"))
            if item["effect"] not in {"read", "write", "irreversible"}:
                raise ValueError("step effect must be read, write or irreversible")
            steps.append(item)
        evidence = " ".join(str(raw.get("evidence", "")).split())[:2000]
        if not evidence:
            raise ValueError("routine needs a final-state verification evidence note")
        status = str(raw.get("status", "candidate"))
        if status != "candidate":
            raise ValueError("new routines are saved as candidates; promotion is a separate action")
        version = int(raw.get("version", 1))
        if version < 1:
            raise ValueError("version must be positive")
        return cls(routine_id, app_id, name, tuple(steps), safe_id(str(raw.get("final_state", ""))),
                   evidence, status, version, time.time())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
