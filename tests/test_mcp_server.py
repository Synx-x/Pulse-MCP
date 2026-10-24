from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pulse.server import McpServer
from pulse.service import PulseService
from pulse.store import Store


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = McpServer(PulseService(Store(self.temp.name)))

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, arguments, request_id=1):
        return self.server.handle({"jsonrpc": "2.0", "id": request_id,
                                   "method": "tools/call",
                                   "params": {"name": name, "arguments": arguments}})

    def test_initialize_and_tools_list(self):
        initialized = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                          "params": {"protocolVersion": "2025-11-25"}})
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
        tools = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        self.assertIn("pulse_map_route", names)
        self.assertIn("pulse_routine_save", names)
        self.assertIn("pulse_browser_observe", names)
        self.assertIn("pulse_browser_click", names)
        self.assertIn("pulse_browser_replay", names)
        self.assertIn("pulse_desktop_observe", names)
        self.assertIn("pulse_desktop_click", names)
        self.assertIn("pulse_desktop_replay", names)

    def test_browser_write_click_requires_effect_authorization(self):
        self.server.service.record_screen({
            "app_id": "browser", "url": "https://example.test/", "title": "Example",
            "viewport": {"width": 800, "height": 600},
            "anchors": [{"id": "submit", "role": "button", "label": "Submit",
                         "bounds": {"x": .4, "y": .4, "width": .2, "height": .1},
                         "actionable": True, "effect": "write"}],
        })
        screen_id = next(iter(self.server.service.store.load_map("browser").screens))
        with self.assertRaises(PermissionError):
            self.server.service.browser_click({"app_id": "browser", "expected_screen": screen_id,
                                                "anchor_id": "submit", "port": 1})

    def test_desktop_write_click_requires_effect_authorization(self):
        self.server.service.record_screen({
            "app_id": "desktop", "url": "", "title": "Desktop",
            "viewport": {"width": 800, "height": 600},
            "anchors": [{"id": "e-3-submit", "role": "button", "label": "Submit",
                         "bounds": {"x": .4, "y": .4, "width": .2, "height": .1},
                         "actionable": True, "effect": "write"}],
        })
        screen_id = next(iter(self.server.service.store.load_map("desktop").screens))
        with self.assertRaises(PermissionError):
            self.server.service.desktop_click({"app_id": "desktop", "expected_screen": screen_id,
                                               "anchor_id": "e-3-submit"})

    def test_record_grid_and_route_through_tools(self):
        first = self.call("pulse_map_record_screen", {
            "app_id": "erp", "url": "https://example.test/home", "title": "Home",
            "viewport": {"width": 1000, "height": 800},
            "anchors": [{"id": "orders", "role": "link", "label": "Orders",
                         "bounds": {"x": .8, "y": .1, "width": .1, "height": .1},
                         "actionable": True}],
        })
        home = json.loads(first["result"]["content"][0]["text"])
        second = self.call("pulse_map_record_screen", {
            "app_id": "erp", "url": "https://example.test/orders", "title": "Orders",
            "viewport": {"width": 1000, "height": 800},
            "anchors": [{"id": "heading", "role": "heading", "label": "Order list",
                         "bounds": {"x": .1, "y": .1, "width": .3, "height": .1}}],
        }, 2)
        orders = json.loads(second["result"]["content"][0]["text"])
        edge = self.call("pulse_map_record_transition", {
            "app_id": "erp", "source": home["screen_id"], "anchor_id": "orders",
            "target": orders["screen_id"], "verified": True,
        }, 3)
        self.assertTrue(json.loads(edge["result"]["content"][0]["text"])["route_eligible"])
        route = self.call("pulse_map_route", {"app_id": "erp", "start": home["screen_id"],
                                               "target": "Order list"}, 4)
        value = json.loads(route["result"]["content"][0]["text"])
        self.assertTrue(value["found"])
        self.assertEqual(value["route"]["transition_count"], 1)

    def test_malformed_tool_inputs_are_reported_as_tool_errors(self):
        result = self.call("pulse_map_record_screen", {"app_id": "../escape"})
        self.assertTrue(result["result"]["isError"])
        self.assertIn("id", result["result"]["content"][0]["text"])

    def test_stdio_is_newline_delimited_json_rpc_only(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PULSE_STATE_DIR=self.temp.name,
                   PYTHONPATH=str(root / "src"))
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        proc = subprocess.run([sys.executable, "-m", "pulse.server"], input="\n".join(
            json.dumps(item) for item in requests) + "\n", text=True, capture_output=True,
            cwd=root, env=env, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2])
        self.assertTrue(all(item["jsonrpc"] == "2.0" for item in responses))


if __name__ == "__main__":
    unittest.main()
