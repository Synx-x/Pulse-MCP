"""Linux desktop adapter backed by the existing computer-use-linux MCP."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import time
from typing import Any

from ..contracts import Bounds, ScreenState


class ComputerUseError(RuntimeError):
    pass


class McpSession:
    """One short-lived stdio MCP session, reused for all steps in a Pulse call."""

    def __init__(self, timeout: float = 20.0):
        binary = os.environ.get("PULSE_COMPUTER_USE_BIN") or shutil.which("computer-use-linux")
        if not binary:
            raise ComputerUseError("computer-use-linux is not installed or not on PATH")
        self.timeout = timeout
        self.process = subprocess.Popen(
            [binary, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0,
        )
        self.buffer = b""
        self.next_id = 0
        try:
            self.request("initialize", {"protocolVersion":"2024-11-05", "capabilities":{},
                                         "clientInfo":{"name":"pulse","version":"0.1.0"}})
            self.notify("notifications/initialized")
        except Exception:
            self.close()
            raise

    def _write(self, value: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise ComputerUseError("computer-use-linux MCP input closed")
        self.process.stdin.write((json.dumps(value, separators=(",", ":")) + "\n").encode())

    def _read_line(self, deadline: float) -> dict[str, Any]:
        while b"\n" not in self.buffer:
            if self.process.stdout is None:
                raise ComputerUseError("computer-use-linux MCP output closed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ComputerUseError("computer-use-linux MCP call timed out")
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                raise ComputerUseError("computer-use-linux MCP call timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise ComputerUseError("computer-use-linux MCP process exited")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComputerUseError("computer-use-linux MCP returned invalid JSON") from exc

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        self._write({"jsonrpc":"2.0", "id":request_id, "method":method, "params":params})
        deadline = time.monotonic() + self.timeout
        while True:
            response = self._read_line(deadline)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise ComputerUseError(response["error"].get("message", "MCP request failed"))
            return response.get("result", {})

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc":"2.0", "method":method, "params":params or {}})

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name":name, "arguments":arguments})
        if result.get("isError"):
            message = next((item.get("text", "") for item in result.get("content", [])
                            if item.get("type") == "text"), "computer-use-linux tool failed")
            raise ComputerUseError(message)
        value = result.get("structuredContent")
        if isinstance(value, dict):
            return {"data":value, "content":result.get("content", [])}
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return {"data":json.loads(item.get("text", "{}")), "content":result.get("content", [])}
                except json.JSONDecodeError:
                    continue
        raise ComputerUseError(f"{name} returned no structured result")

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def _label(raw: dict[str, Any]) -> str:
    return " ".join(str(raw.get("name") or "").split())[:240]


def _ocr_boxes(image: bytes) -> list[dict[str, Any]]:
    binary = shutil.which("tesseract")
    if not binary or not image:
        return []
    try:
        result = subprocess.run([binary, "stdin", "stdout", "tsv"], input=image,
                                capture_output=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for line in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 12 or parts[0] != "5" or not parts[11].strip():
            continue
        try:
            conf = float(parts[10])
            left, top, width, height = (int(parts[i]) for i in (6, 7, 8, 9))
        except ValueError:
            continue
        if conf < 35 or width <= 0 or height <= 0:
            continue
        key = (parts[2], parts[3], parts[4])
        groups.setdefault(key, []).append({"text":parts[11].strip(), "x":left, "y":top,
                                           "width":width, "height":height, "confidence":conf})
    boxes = []
    for words in groups.values():
        for first in range(len(words)):
            for last in range(first + 1, min(len(words), first + 6) + 1):
                phrase = words[first:last]
                x, y = min(w["x"] for w in phrase), min(w["y"] for w in phrase)
                right = max(w["x"] + w["width"] for w in phrase)
                bottom = max(w["y"] + w["height"] for w in phrase)
                boxes.append({"text":" ".join(w["text"] for w in phrase), "x":x, "y":y,
                              "width":right-x, "height":bottom-y,
                              "confidence":sum(w["confidence"] for w in phrase)/len(phrase)})
    return boxes


def _match_ocr(label: str, boxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted = re.sub(r"[^a-z0-9]+", "", label.casefold())
    if len(wanted) < 2:
        return None
    exact, partial = [], []
    for box in boxes:
        candidate = re.sub(r"[^a-z0-9]+", "", box["text"].casefold())
        if candidate == wanted:
            exact.append(box)
        elif len(candidate) > len(wanted) and wanted in candidate:
            partial.append(box)
    if exact:
        return max(exact, key=lambda item:item["confidence"])
    return min(partial, key=lambda item:(len(item["text"]), -item["confidence"]), default=None)


def _sway_geometry(application: str | None) -> tuple[dict[str, int] | None, dict[str, int] | None]:
    """Read the isolated Sway output and app rectangle when CUL has local bounds."""
    if not os.environ.get("SWAYSOCK") or os.environ.get("CUL_NESTED") != "1":
        return None, None
    binary = shutil.which("swaymsg")
    if not binary:
        return None, None
    try:
        tree = subprocess.run([binary, "-t", "get_tree", "-r"], capture_output=True,
                              timeout=1, check=True).stdout
        outputs = subprocess.run([binary, "-t", "get_outputs", "-r"], capture_output=True,
                                  timeout=1, check=True).stdout
        tree_data, output_data = json.loads(tree), json.loads(outputs)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None, None
    size = None
    for output in output_data:
        if output.get("active") and output.get("current_mode"):
            mode = output["current_mode"]
            size = {"width":int(mode.get("width", 0)), "height":int(mode.get("height", 0))}
            break
    queue = [tree_data]
    windows = []
    while queue:
        node = queue.pop()
        if node.get("pid") and node.get("rect"):
            windows.append(node)
        queue.extend(node.get("nodes", []))
        queue.extend(node.get("floating_nodes", []))
    matched = next((node for node in windows if application and
                    node.get("app_id", "").casefold() == application.casefold()), None)
    if matched is None and application:
        matched = next((node for node in windows if application.casefold() in
                        str(node.get("name", "")).casefold()), None)
    rect = matched.get("rect") if matched else None
    if not rect or not rect.get("width") or not rect.get("height"):
        return size, None
    return size, {key:int(rect[key]) for key in ("x", "y", "width", "height")}


class ComputerUseDriver:
    """Expose the active desktop as normalized semantic and visual anchors."""

    def __init__(self, session: McpSession | None = None):
        self.session = session or McpSession()

    def observe(self, app_id: str, *, screenshot: bool = True,
                application: str | None = None,
                map_hint: ScreenState | None = None) -> dict[str, Any]:
        arguments: dict[str, Any] = {"include_screenshot":screenshot, "verbose":False}
        if application:
            arguments["app_name_or_bundle_identifier"] = application
        response = self.session.tool("get_app_state", arguments)
        data, content = response["data"], response["content"]
        summary = data.get("screenshot") or {}
        width, height = summary.get("coordinate_width"), summary.get("coordinate_height")
        sway_size, window_rect = _sway_geometry(application)
        if not width or not height:
            size = sway_size or (map_hint.viewport if map_hint else None)
            if not size:
                raise ComputerUseError("desktop screenshot or display has no coordinate dimensions")
            width, height = size["width"], size["height"]
        image_data = next((item.get("data") for item in content
                           if item.get("type") == "image" and item.get("data")), None)
        image = base64.b64decode(image_data) if image_data else b""
        boxes = _ocr_boxes(image) if image else []
        anchors = []
        for node in data.get("accessibility_tree", []):
            role = str(node.get("role") or "unknown").strip().lower()
            label = _label(node)
            bounds = node.get("bounds") or {}
            actions = {str(item.get("name", "")).casefold() for item in node.get("actions", [])}
            actionable = bool(actions & {"click", "press", "activate", "toggle", "set_value"}) or bool(node.get("supports_editable_text"))
            source = "accessibility"
            rect = None
            pixel_bounds = dict(bounds)
            # CUL's nested Sway AT-SPI coordinates are window-local. Convert
            # them to screenshot coordinates with the compositor's window rect.
            if window_rect and (int(bounds.get("x", 0)) != 0 or int(bounds.get("y", 0)) != 0):
                pixel_bounds["x"] = int(bounds["x"]) + window_rect["x"]
                pixel_bounds["y"] = int(bounds["y"]) + window_rect["y"]
            try:
                rect = Bounds.from_pixels(pixel_bounds, {"width":width, "height":height})
            except (KeyError, TypeError, ValueError):
                pass
            index = int(node.get("index", 0))
            token = hashlib.sha256(f"{role}\0{label.casefold()}\0{index}".encode()).hexdigest()[:12]
            anchor_id = f"e-{index}-{token}"
            needs_visual = rect is None or (float(bounds.get("x", 0)) == 0
                                            and float(bounds.get("y", 0)) == 0)
            if actionable and label and screenshot and needs_visual:
                visual = _match_ocr(label, boxes)
                if visual:
                    rect = Bounds.from_pixels(visual, {"width":width, "height":height})
                    source = "vision"
            if rect is None or (float(bounds.get("x", 0)) == 0
                                and float(bounds.get("y", 0)) == 0):
                hint = next((a for a in map_hint.anchors if a.id == anchor_id), None) if map_hint else None
                if hint:
                    rect, source = hint.bounds, hint.source
            if not label:
                continue
            if rect is None:
                continue
            state = {str(item).casefold() for item in node.get("states", [])}
            anchors.append({"id":f"e-{index}-{token}", "role":role, "label":label,
                            "bounds":{"x":rect.x,"y":rect.y,"width":rect.width,"height":rect.height},
                            "source":source, "actionable":actionable,
                            "effect":"write" if actionable else "read",
                            "selected":bool(state & {"selected", "checked"}),
                            "confidence":0.8 if source == "vision" else 1.0})
        title = (data.get("window_context") or {}).get("title") or (map_hint.title if map_hint else "Desktop")
        return {"app_id":app_id, "url":"", "title":title,
                "viewport":{"width":int(width),"height":int(height)}, "anchors":anchors,
                "screenshot_sha256":hashlib.sha256(image).hexdigest() if image else None,
                "observed_at":time.time()}

    def click(self, x: float, y: float) -> dict[str, Any]:
        response = self.session.tool("click", {"x":round(x), "y":round(y), "button":"left"})
        return response["data"]

    def close(self) -> None:
        self.session.close()
