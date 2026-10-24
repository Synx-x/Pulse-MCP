from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from pulse.drivers.browser import field_rejection, redact
from pulse.contracts import ScreenState
from pulse.server import McpServer
from pulse.service import (MAX_SCROLL_PIXELS, PulseService, screen_id_at,
                           scroll_anchor, scroll_deltas)
from pulse.store import Store


def observation(*anchors, title="Form", url="https://example.test/form", width=800, height=600):
    return {"app_id": "browser", "url": url, "title": title,
            "viewport": {"width": width, "height": height},
            "anchors": list(anchors), "screenshot_sha256": None}


def field(anchor_id="email", label="Email", role="input", *, effect="write", x=.2, y=.2):
    return {"id": anchor_id, "role": role, "label": label,
            "bounds": {"x": x, "y": y, "width": .3, "height": .06},
            "source": "dom", "actionable": True, "effect": effect}


class FakeDriver:
    """Stand-in for BrowserDriver. Records every page call the service makes."""

    calls: list[tuple] = []

    def __init__(self, port=9222, **_):
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def observe(self, app_id, *, screenshot_digest=True):
        FakeDriver.calls.append(("observe", app_id))
        if FakeDriver.observation_sequence:
            return dict(FakeDriver.observation_sequence.pop(0))
        return dict(FakeDriver.next_observation)

    def inspect_field(self, x, y):
        FakeDriver.calls.append(("inspect", x, y))
        return dict(FakeDriver.next_field)

    def focus_field(self, x, y):
        FakeDriver.calls.append(("focus", x, y))
        return FakeDriver.focus_ok

    def insert_text(self, value):
        FakeDriver.calls.append(("insert_text", value))

    def confirm_entry(self, expected_length):
        FakeDriver.calls.append(("confirm", expected_length))
        if not FakeDriver.confirm_ok:
            return {"found": FakeDriver.confirm_found, "filled": False}
        return {"found": True, "filled": True}

    def blur_field(self):
        FakeDriver.calls.append(("blur",))

    def focused_tag(self):
        FakeDriver.calls.append(("focused_tag",))
        return FakeDriver.focused

    def entry_text(self, value):
        FakeDriver.calls.append(("entry_text",))
        return value.strip("\r\n")

    def entry_problem(self, value):
        FakeDriver.calls.append(("entry_problem",))
        return FakeDriver.entry_problem_code

    def press_key(self, name):
        FakeDriver.calls.append(("press_key", name))

    def scroll_by(self, dx, dy):
        FakeDriver.calls.append(("scroll_by", dx, dy))
        return FakeDriver.next_scroll

    def click(self, x, y):
        raise AssertionError("fill and scroll must not click")

    def close(self):
        FakeDriver.calls.append(("close",))


class BrowserFillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = PulseService(Store(self.temp.name))
        FakeDriver.calls = []
        FakeDriver.observation_sequence = []
        FakeDriver.next_observation = observation(field())
        FakeDriver.next_field = {"found": True, "tag": "input", "type": "text",
                                 "disabled": False, "readonly": False, "editable": False}
        FakeDriver.focus_ok = True
        FakeDriver.confirm_ok = True
        FakeDriver.confirm_found = True
        FakeDriver.focused = "input"
        FakeDriver.entry_problem_code = None
        FakeDriver.next_scroll = {"before": {"x": 0, "y": 0}, "after": {"x": 0, "y": 300},
                                  "max": {"x": 0, "y": 900}}
        self.screen_id = self.service.record_screen(observation(field()))["screen_id"]
        self.patcher = patch("pulse.service.BrowserDriver", FakeDriver)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def fill(self, **overrides):
        args = {"app_id": "browser", "expected_screen": self.screen_id,
                "anchor_id": "email", "value": "ada@example.test",
                "authorized_effects": ["write"], "port": 9222}
        args.update(overrides)
        return self.service.browser_fill(args)

    def test_fill_requires_write_authorization(self):
        with self.assertRaises(PermissionError):
            self.fill(authorized_effects=[])
        with self.assertRaises(PermissionError):
            self.fill(authorized_effects=["irreversible"])
        self.assertEqual([c for c in FakeDriver.calls if c[0] == "inspect"], [])

    def test_fill_rejects_unknown_or_unmapped_anchor(self):
        with self.assertRaises(KeyError):
            self.fill(expected_screen="s-00000000000000000000")
        with self.assertRaises(ValueError):
            self.fill(anchor_id="absent")

    def test_fill_rejects_a_non_field_role(self):
        button = field("go", "Submit", role="button")
        self.screen_id = self.service.record_screen(observation(button))["screen_id"]
        FakeDriver.next_observation = observation(button)
        with self.assertRaisesRegex(ValueError, "not a fillable field"):
            self.fill(anchor_id="go")

    def test_fill_requires_a_non_empty_value(self):
        with self.assertRaises(ValueError):
            self.fill(value="")
        with self.assertRaises(ValueError):
            self.fill(value=None)

    def test_fill_returns_the_length_only_and_never_the_value(self):
        result = self.fill()
        self.assertTrue(result["filled"])
        self.assertEqual(result["value_length"], len("ada@example.test"))
        self.assertFalse(result["submitted"])
        serialized = json.dumps(result)
        self.assertNotIn("ada@example.test", serialized)
        self.assertNotIn("@", serialized.split("observed_url")[0])

    def test_fill_never_persists_the_value(self):
        self.fill()
        stored = (Store(self.temp.name).root
                  / "maps" / "browser.json").read_text(encoding="utf-8")
        self.assertNotIn("ada@example.test", stored)

    def test_fill_types_into_the_focused_field_and_confirms_by_length(self):
        self.fill()
        inserts = [c for c in FakeDriver.calls if c[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", "ada@example.test")])
        self.assertIn(("confirm", len("ada@example.test")), FakeDriver.calls)
        self.assertNotIn("click", [c[0] for c in FakeDriver.calls])

    def test_fill_refuses_a_disabled_field_and_does_not_type(self):
        FakeDriver.next_field = {"found": True, "tag": "input", "type": "text",
                                 "disabled": True, "readonly": False, "editable": False}
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.fill()
        self.assertNotIn("insert_text", [c[0] for c in FakeDriver.calls])

    def test_fill_refuses_a_readonly_field(self):
        FakeDriver.next_field = {"found": True, "tag": "input", "type": "text",
                                 "disabled": False, "readonly": True, "editable": False}
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.fill()
        self.assertNotIn("insert_text", [c[0] for c in FakeDriver.calls])

    def test_fill_stops_on_a_stale_screen(self):
        FakeDriver.next_observation = observation(field(), title="Other page")
        with self.assertRaisesRegex(ValueError, "stale map"):
            self.fill()
        self.assertNotIn("insert_text", [c[0] for c in FakeDriver.calls])

    def test_fill_stops_when_focus_or_entry_is_not_confirmed(self):
        FakeDriver.focus_ok = False
        with self.assertRaisesRegex(ValueError, "refused focus"):
            self.fill()
        FakeDriver.focus_ok = True
        FakeDriver.confirm_ok = False
        with self.assertRaisesRegex(ValueError, "did not confirm"):
            self.fill()

    def test_fill_forgets_focus_before_it_observes(self):
        self.fill()
        names = [call[0] for call in FakeDriver.calls]
        self.assertIn("blur", names)
        self.assertLess(names.index("blur"), len(names) - 1 - names[::-1].index("observe"))

    def test_fill_names_a_lost_focus_separately_from_a_wrong_length(self):
        FakeDriver.confirm_ok = False
        FakeDriver.confirm_found = False
        with self.assertRaisesRegex(ValueError, "lost focus"):
            self.fill()
        self.assertNotIn("blur", [call[0] for call in FakeDriver.calls])

    def test_fill_reports_a_masked_field_without_leaking_the_value(self):
        FakeDriver.entry_problem_code = "mismatch"
        with self.assertRaises(ValueError) as raised:
            self.fill(value="+1 555 0100")
        self.assertNotIn("555", str(raised.exception))
        self.assertIn("changed the text", str(raised.exception))

    def test_keep_focus_leaves_the_field_ready_for_a_key(self):
        result = self.fill(keep_focus=True)
        self.assertFalse(result["blurred"])
        self.assertNotIn("blur", [call[0] for call in FakeDriver.calls])

    def test_a_fill_without_keep_focus_blurs_and_says_so(self):
        self.assertTrue(self.fill()["blurred"])

    def test_the_value_is_trimmed_for_a_single_line_field(self):
        self.fill(value="bench-item\n")
        inserts = [c for c in FakeDriver.calls if c[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", "bench-item")])


class BrowserScreenIdentityTests(unittest.TestCase):
    def test_a_scrolled_position_gets_its_own_screen_id(self):
        top = {**observation(field()), "scroll": {"x": 0, "y": 0}}
        moved = {**observation(field()), "scroll": {"x": 0, "y": 600}}
        self.assertNotEqual(screen_id_at(top), screen_id_at(moved))

    def test_the_same_offset_is_stable(self):
        moved = {**observation(field()), "scroll": {"x": 0, "y": 600}}
        self.assertEqual(screen_id_at(moved), screen_id_at(dict(moved)))

    def test_an_unscrolled_page_keeps_its_plain_identity(self):
        plain = observation(field())
        self.assertEqual(screen_id_at(plain), ScreenState.create(plain).id)
        self.assertEqual(screen_id_at({**plain, "scroll": {"x": 0, "y": 0}}),
                         ScreenState.create(plain).id)

    def test_the_offset_survives_url_scrubbing(self):
        """A screen identity drops query and fragment, so the offset rides beside it."""
        first = {**observation(field(), url="https://example.test/x?token=1"),
                 "scroll": {"x": 0, "y": 300}}
        second = {**observation(field(), url="https://example.test/x?token=2"),
                  "scroll": {"x": 0, "y": 300}}
        self.assertEqual(screen_id_at(first), screen_id_at(second))
        self.assertNotEqual(screen_id_at(first),
                            screen_id_at({**first, "scroll": {"x": 0, "y": 0}}))


class BrowserKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = PulseService(Store(self.temp.name))
        FakeDriver.calls = []
        FakeDriver.observation_sequence = []
        FakeDriver.next_observation = observation(field())
        self.screen_id = self.service.record_screen(observation(field()))["screen_id"]
        self.patcher = patch("pulse.service.BrowserDriver", FakeDriver)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def press(self, **overrides):
        args = {"app_id": "browser", "expected_screen": self.screen_id,
                "key": "enter", "authorized_effects": ["write"], "port": 9222}
        args.update(overrides)
        return self.service.browser_key(args)

    def test_enter_needs_write_authorization(self):
        with self.assertRaises(PermissionError):
            self.press(authorized_effects=[])
        self.assertNotIn("press_key", [call[0] for call in FakeDriver.calls])

    def test_only_allowlisted_keys_are_sent(self):
        for bad in ("ctrl+a", "a", "tab", "", "Backspace"):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                self.press(key=bad)
        self.assertNotIn("press_key", [call[0] for call in FakeDriver.calls])

    def test_enter_is_sent_once_on_the_expected_screen(self):
        FakeDriver.observation_sequence = [observation(field()),
                                           observation(field(), title="Submitted")]
        result = self.press()
        self.assertEqual([c for c in FakeDriver.calls if c[0] == "press_key"],
                         [("press_key", "enter")])
        self.assertEqual(result["sent"], "enter")
        self.assertTrue(result["state_changed"])

    def test_a_key_press_stops_on_a_stale_screen(self):
        FakeDriver.next_observation = observation(field(), title="Other page")
        with self.assertRaisesRegex(ValueError, "stale map"):
            self.press()
        self.assertNotIn("press_key", [call[0] for call in FakeDriver.calls])


class FieldRejectionTests(unittest.TestCase):
    def test_unsafe_and_non_text_fields_are_rejected(self):
        base = {"found": True, "disabled": False, "readonly": False, "editable": False}
        cases = {
            "password": ({"tag": "input", "type": "password"}, "type_password"),
            "file": ({"tag": "input", "type": "file"}, "type_file"),
            "hidden": ({"tag": "input", "type": "hidden"}, "type_hidden"),
            "checkbox": ({"tag": "input", "type": "checkbox"}, "type_checkbox"),
            "radio": ({"tag": "input", "type": "radio"}, "type_radio"),
            "submit": ({"tag": "input", "type": "submit"}, "not_fillable"),
            "button": ({"tag": "input", "type": "button"}, "not_fillable"),
        }
        for name, (extra, expected) in cases.items():
            with self.subTest(field=name):
                reason = field_rejection({**base, **extra})
                self.assertIsNotNone(reason)
                self.assertEqual(reason, expected)

    def test_text_fields_are_accepted(self):
        base = {"found": True, "disabled": False, "readonly": False}
        for tag, kind, editable in (("input", "text", False), ("input", "email", False),
                                    ("input", "search", False), ("textarea", "", False),
                                    ("div", "", True)):
            with self.subTest(tag=tag, kind=kind):
                self.assertIsNone(field_rejection({**base, "tag": tag, "type": kind,
                                                   "editable": editable}))

    def test_missing_element_is_rejected(self):
        self.assertEqual(field_rejection({"found": False}), "no_field")

    def test_button_like_target_is_named_even_without_a_containing_field(self):
        point = {"found": False, "disabled": False, "readonly": False}
        self.assertEqual(field_rejection({**point, "tag": "input", "type": "submit"}), "not_fillable")
        self.assertEqual(field_rejection({**point, "tag": "button", "type": "submit"}), "not_fillable")
        self.assertEqual(field_rejection({**point, "tag": "span", "type": ""}), "not_fillable")

    def test_redact_removes_the_value_from_anchor_labels(self):
        raw = observation({"id": "e1", "role": "heading", "label": "typed ada@example.test here",
                           "bounds": {"x": .1, "y": .1, "width": .2, "height": .05}})
        cleaned = redact(raw, "ada@example.test")
        self.assertNotIn("ada@example.test", json.dumps(cleaned))
        self.assertIn("[redacted]", cleaned["anchors"][0]["label"])
        self.assertEqual(raw["anchors"][0]["label"], "typed ada@example.test here")


class BrowserScrollTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = PulseService(Store(self.temp.name))
        FakeDriver.calls = []
        FakeDriver.observation_sequence = []
        FakeDriver.next_observation = observation(field())
        self.screen_id = self.service.record_screen(observation(field()))["screen_id"]
        self.patcher = patch("pulse.service.BrowserDriver", FakeDriver)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def scroll(self, **overrides):
        args = {"app_id": "browser", "expected_screen": self.screen_id, "dy": 300, "port": 9222}
        args.update(overrides)
        return self.service.browser_scroll(args)

    def test_scroll_returns_the_new_offset_and_mapped_screen(self):
        result = self.scroll()
        self.assertTrue(result["scrolled"])
        self.assertEqual(result["offset_after"], {"x": 0, "y": 300})
        self.assertEqual(result["moved"], {"x": 0, "y": 300})
        self.assertEqual(result["from_screen"], self.screen_id)
        self.assertIn("grid", result)
        self.assertIn("anchors", result)

    def test_scroll_records_a_transition_when_the_view_changes(self):
        scrolled = {"id": "below", "role": "heading", "label": "Second section",
                    "bounds": {"x": .1, "y": .1, "width": .4, "height": .05}}
        FakeDriver.observation_sequence = [observation(field()),
                                           observation(scrolled, title="Form")]
        result = self.scroll()
        self.assertTrue(result["state_changed"])
        self.assertNotEqual(result["to_screen"], self.screen_id)

    def test_scroll_rejects_out_of_range_and_malformed_deltas(self):
        for bad in ({"dy": MAX_SCROLL_PIXELS + 1}, {"dx": -MAX_SCROLL_PIXELS - 1},
                    {"dy": "down"}, {"dy": float("nan")}, {"dy": 0, "dx": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.scroll(**bad)
        self.assertNotIn("scroll_by", [c[0] for c in FakeDriver.calls])

    def test_scroll_requires_a_mapped_screen_and_current_state(self):
        with self.assertRaises(KeyError):
            self.scroll(expected_screen="s-00000000000000000000")
        FakeDriver.next_observation = observation(field(), title="Other page")
        with self.assertRaisesRegex(ValueError, "stale map"):
            self.scroll()
        self.assertNotIn("scroll_by", [c[0] for c in FakeDriver.calls])

    def test_scroll_accepts_a_named_tool_call(self):
        server = McpServer(self.service)
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "pulse_browser_scroll",
                                             "arguments": {"app_id": "browser",
                                                           "expected_screen": self.screen_id,
                                                           "dy": -120}}})
        value = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(value["dy"], -120)


class ToolRegistrationTests(unittest.TestCase):
    def test_fill_and_scroll_are_advertised(self):
        tools = McpServer(PulseService(Store(tempfile.mkdtemp()))).handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        self.assertIn("pulse_browser_fill", by_name)
        self.assertIn("pulse_browser_scroll", by_name)
        fill = by_name["pulse_browser_fill"]["inputSchema"]
        self.assertEqual(set(fill["required"]),
                         {"expected_screen", "anchor_id", "value", "authorized_effects"})
        scroll = by_name["pulse_browser_scroll"]["inputSchema"]
        self.assertEqual(scroll["required"], ["expected_screen"])


class BrowserScrollRouteTests(unittest.TestCase):
    """A scroll must join a route, because a scroll edge names no page anchor."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = PulseService(Store(self.temp.name))
        FakeDriver.calls = []
        FakeDriver.observation_sequence = []
        FakeDriver.next_scroll = {"before": {"x": 0, "y": 0}, "after": {"x": 0, "y": 1200},
                                  "max": {"x": 0, "y": 3000}}
        self.patcher = patch("pulse.service.BrowserDriver", FakeDriver)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_a_scroll_records_a_verified_edge_named_by_its_deltas(self):
        top = {**observation(field()), "scroll": {"x": 0, "y": 0}}
        self.service.record_screen(top)
        moved = {**observation(field()), "scroll": {"x": 0, "y": 1200}}
        FakeDriver.observation_sequence = [top, moved]
        top_id = screen_id_at(top)
        bottom_id = screen_id_at(moved)
        self.service.record_screen(moved)
        result = self.service.browser_scroll({"app_id": "browser", "expected_screen": top_id,
                                              "dy": 1200, "port": 9222})
        self.assertEqual(result["to_screen"], bottom_id)
        edges = [e for e in self.service.store.load_map("browser").transitions]
        self.assertIn(bottom_id, [e.target for e in edges])
        self.assertEqual(scroll_deltas(edges[-1].anchor_id), (0.0, 1200.0))

    def test_the_delta_name_round_trips_and_rejects_plain_anchors(self):
        self.assertEqual(scroll_deltas(scroll_anchor(0, -400)), (0.0, -400.0))
        self.assertIsNone(scroll_deltas("a-61e2c1a1c6d312a9"))
        self.assertIsNone(scroll_deltas("scroll"))


if __name__ == "__main__":
    unittest.main()
