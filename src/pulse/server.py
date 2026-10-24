"""Minimal MCP stdio server. Stdout contains JSON-RPC only; diagnostics use stderr."""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .service import PulseService

PROTOCOL_VERSION = "2025-11-25"

_TOOLS: dict[str, tuple[str, dict[str, Any], str]] = {
    "pulse_map_record_screen": (
        "Record a screen observation with normalized anchors and return its grid.",
        {"type": "object", "required": ["app_id", "url", "title", "viewport", "anchors"],
         "properties": {
             "app_id": {"type": "string"}, "url": {"type": "string"},
             "title": {"type": "string"},
             "viewport": {"type": "object", "required": ["width", "height"],
                          "properties": {"width": {"type": "integer"}, "height": {"type": "integer"}}},
             "anchors": {"type": "array", "items": {"type": "object"}},
             "columns": {"type": "integer", "minimum": 1, "maximum": 64},
             "rows": {"type": "integer", "minimum": 1, "maximum": 64},
             "screenshot_sha256": {"type": "string"},
         }}, "record_screen"),
    "pulse_map_record_transition": (
        "Record a transition. Only verified transitions are used by route planning.",
        {"type": "object", "required": ["app_id", "source", "anchor_id", "target", "verified"],
         "properties": {"app_id": {"type": "string"}, "source": {"type": "string"},
                        "anchor_id": {"type": "string"}, "target": {"type": "string"},
                        "verified": {"type": "boolean"}}}, "record_transition"),
    "pulse_map_get": (
        "Read a stored screen map, optionally including one screen's full grid.",
        {"type": "object", "required": ["app_id"],
         "properties": {"app_id": {"type": "string"}, "screen_id": {"type": "string"}}}, "get_map"),
    "pulse_map_route": (
        "Find the shortest verified route from a mapped screen to a screen or anchor label.",
        {"type": "object", "required": ["app_id", "start", "target"],
         "properties": {"app_id": {"type": "string"}, "start": {"type": "string"},
                        "target": {"type": "string"}}}, "route"),
    "pulse_routine_save": (
        "Save a successfully verified routine as a reviewable candidate; this does not execute it.",
        {"type": "object", "required": ["id", "app_id", "name", "steps", "final_state", "evidence"],
         "properties": {"id": {"type": "string"}, "app_id": {"type": "string"},
                        "name": {"type": "string"}, "steps": {"type": "array", "items": {"type": "object"}},
                        "final_state": {"type": "string"}, "evidence": {"type": "string"}}}, "save_routine"),
    "pulse_routine_list": (
        "List saved routine candidates, optionally filtered by application.",
        {"type": "object", "properties": {"app_id": {"type": "string"}}}, "list_routines"),
    "pulse_routine_get": (
        "Read a saved routine candidate by id.",
        {"type": "object", "required": ["routine_id"],
         "properties": {"routine_id": {"type": "string"}}}, "get_routine"),
    "pulse_browser_observe": (
        "Observe the active local Chromium page, map visible DOM controls into the spatial grid and store the screen.",
        {"type": "object", "properties": {"app_id": {"type": "string"},
          "port": {"type": "integer", "minimum": 1, "maximum": 65535}}}, "browser_observe"),
    "pulse_browser_click": (
        "Click a mapped browser control only if the current screen still matches the expected map state. Write and irreversible controls require explicit authorization.",
        {"type": "object", "required": ["expected_screen", "anchor_id"],
         "properties": {"app_id": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
           "expected_screen": {"type": "string"}, "anchor_id": {"type": "string"},
           "authorized_effects": {"type": "array", "items": {"type": "string", "enum": ["write", "irreversible"]}}}}, "browser_click"),
    "pulse_browser_fill": (
        "Type a value into one mapped browser field. The value applies to this call only, is never stored or returned, and never submits the form. Requires authorized_effects:[\"write\"]. Password, file, hidden, checkbox, radio, disabled and read-only fields are refused. Set keep_focus when a fill is followed by pulse_browser_key, because a fill drops focus by default to keep the value out of the map.",
        {"type": "object", "required": ["expected_screen", "anchor_id", "value", "authorized_effects"],
         "properties": {"app_id": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
           "expected_screen": {"type": "string"}, "anchor_id": {"type": "string"},
           "value": {"type": "string"}, "keep_focus": {"type": "boolean"},
           "authorized_effects": {"type": "array", "items": {"type": "string", "enum": ["write", "irreversible"]}}}}, "browser_fill"),
    "pulse_browser_scroll": (
        "Scroll the current browser viewport by a bounded pixel delta and map the resulting screen. The scroll acts only on the viewport of the expected mapped screen.",
        {"type": "object", "required": ["expected_screen"],
         "properties": {"app_id": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
           "expected_screen": {"type": "string"},
           "dx": {"type": "number"}, "dy": {"type": "number"}}}, "browser_scroll"),
    "pulse_browser_key": (
        "Send one allowlisted key, enter or escape, to the focused element on the expected screen. Enter submits the form that holds the focused field. Requires authorized_effects:[\"write\"].",
        {"type": "object", "required": ["expected_screen", "key", "authorized_effects"],
         "properties": {"app_id": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
           "expected_screen": {"type": "string"},
           "key": {"type": "string", "enum": ["enter", "escape"]},
           "authorized_effects": {"type": "array", "items": {"type": "string", "enum": ["write", "irreversible"]}}}}, "browser_key"),
    "pulse_browser_replay": (
        "Execute a previously verified route in one browser call. Each step checks its expected screen and stops on divergence. Write and irreversible effects require explicit authorization.",
        {"type": "object", "required": ["start", "target"],
         "properties": {"app_id": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
           "start": {"type": "string"}, "target": {"type": "string"},
           "authorized_effects": {"type": "array", "items": {"type": "string", "enum": ["write", "irreversible"]}}}}, "browser_replay"),
    "pulse_desktop_observe": (
        "Capture the active Linux desktop through computer-use-linux, map accessibility controls to a normalized screen grid, and use OCR for anchors when accessibility bounds are missing.",
        {"type":"object", "properties":{"app_id":{"type":"string"},
          "application":{"type":"string"}}}, "desktop_observe"),
    "pulse_desktop_click": (
        "Click an anchored desktop control only when the live desktop still matches the expected mapped screen. Write effects require explicit authorization.",
        {"type":"object", "required":["expected_screen","anchor_id"],
         "properties":{"app_id":{"type":"string"}, "application":{"type":"string"},
          "expected_screen":{"type":"string"}, "anchor_id":{"type":"string"},
          "authorized_effects":{"type":"array", "items":{"type":"string", "enum":["write","irreversible"]}}}}, "desktop_click"),
    "pulse_desktop_replay": (
        "Execute a verified desktop route in one call. Each step checks the expected mapped screen and stops on divergence. Write effects require explicit authorization.",
        {"type":"object", "required":["start","target"],
         "properties":{"app_id":{"type":"string"}, "application":{"type":"string"},
          "start":{"type":"string"}, "target":{"type":"string"},
          "authorized_effects":{"type":"array", "items":{"type":"string", "enum":["write","irreversible"]}}}}, "desktop_replay"),
}


class McpServer:
    def __init__(self, service: PulseService | None = None):
        self.service = service or PulseService()

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        is_notification = "id" not in request
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            requested = (request.get("params") or {}).get("protocolVersion", PROTOCOL_VERSION)
            version = requested if requested in {PROTOCOL_VERSION, "2025-06-18", "2024-11-05"} else PROTOCOL_VERSION
            return self._result(request_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "pulse", "version": "0.1.0"},
                "instructions": "Pulse maps screens into normalized grids and routes only through verified transitions. Saved routines remain candidates until separately reviewed.",
            })
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            tools = [{"name": name, "description": description, "inputSchema": schema}
                     for name, (description, schema, _) in _TOOLS.items()]
            return self._result(request_id, {"tools": tools})
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if name not in _TOOLS:
                result = self._tool_error(f"unknown tool: {name}")
            else:
                args = params.get("arguments", {})
                if not isinstance(args, dict):
                    result = self._tool_error("arguments must be an object")
                else:
                    handler_name = _TOOLS[name][2]
                    handler: Callable[[dict[str, Any]], Any] = getattr(self.service, handler_name)
                    try:
                        value = handler(args)
                        result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
                        if value is None:
                            result["isError"] = True
                    except (ValueError, KeyError, TypeError, PermissionError) as exc:
                        result = self._tool_error(str(exc))
                    except Exception as exc:  # keep the transport alive; details stay on stderr
                        print(f"Pulse tool {name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                        result = self._tool_error("internal tool error")
            return self._result(request_id, result)
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"}}

    @staticmethod
    def _tool_error(message: str) -> dict[str, Any]:
        return {"isError": True, "content": [{"type": "text", "text": message}]}

    @staticmethod
    def _result(request_id: Any, value: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": value}


def main() -> None:
    server = McpServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("expected a JSON-RPC 2.0 object")
            response = server.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            print(f"Pulse MCP input error: {type(exc).__name__}: {exc}", file=sys.stderr)
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "parse error"}}
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
