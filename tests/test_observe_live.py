"""The observation script, run against a real DOM through Chromium's CDP.

The unit tests stub the driver, so they cannot catch a selector mistake in the
in-page script. These tests evaluate the same script against a real page and
assert on the anchors it returns. They skip when no Chromium answers.

Set PULSE_TEST_CDP_PORT to a debugging port. The page is a data: URL, so the
tests need no network and touch no profile.
"""
from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request

from pulse.drivers.browser import _OBSERVE

PORT = int(os.environ.get("PULSE_TEST_CDP_PORT", "9299"))

# Ports a timing run or a bench harness may hold. This live test navigates the
# browser that answers its port, so it must never land on one of those: it
# replaces the page under test and corrupts the run.
RESERVED_PORTS = frozenset({9251, 9252, 9299})


def endpoint_answers(port: int) -> bool:
    """True when a Chromium debugging endpoint answers on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.0):
            return True
    except (OSError, urllib.error.URLError, ValueError):
        return False

PAGE = """<!doctype html><title>Fixture</title>
<style>
  .hid { opacity: 0; width: 40px; height: 40px; position: absolute; top: 60px; left: 60px; }
  .row { position: relative; padding: 8px; }
</style>
<div class="row">
  <input class="hid" type="checkbox" id="styled">
  <label for="styled">Styled task</label>
</div>
<div class="row">
  <input type="checkbox" id="plain">
  <label for="plain">Plain task</label>
</div>
<button id="go">Add Element</button>
<button id="outline" class="selected">TaskList</button>
<input id="field" placeholder="New Todo Input">
"""


@unittest.skipUnless(PORT not in RESERVED_PORTS,
                     f"port {PORT} is reserved for a timing run; set PULSE_TEST_CDP_PORT")
@unittest.skipUnless(endpoint_answers(PORT), f"no Chromium on port {PORT}")
class LiveObserveTests(unittest.TestCase):
    """One real page, observed through the real script."""

    @classmethod
    def setUpClass(cls):
        from pulse.drivers.browser import BrowserDriver
        cls.driver = BrowserDriver(PORT)
        # Write the fixture into a blank page. A data: URL carrying newlines is
        # rejected by the navigation call, and a fixture needs no network.
        cls.driver.cdp.send("Page.navigate", {"url": "about:blank"})
        cls.driver.cdp.send("Runtime.evaluate", {
            "expression": "document.open();document.write(%s);document.close();" % json.dumps(PAGE)})
        import time
        time.sleep(0.4)
        cls.raw = cls.driver.evaluate(_OBSERVE)

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()

    def anchors(self, role=None):
        return [a for a in self.raw["anchors"] if role is None or a["role"] == role]

    def test_a_styled_checkbox_is_mapped_with_its_label(self):
        labels = [a["label"] for a in self.anchors("checkbox")]
        self.assertEqual(labels, ["Styled task", "Plain task"])

    def test_the_styled_checkbox_keeps_its_own_click_target(self):
        styled = self.anchors("checkbox")[0]
        self.assertGreater(styled["bounds"]["width"], 0.03)
        self.assertLess(styled["bounds"]["y"], 0.3)

    def test_a_bare_label_does_not_duplicate_its_control(self):
        labels = [a["label"] for a in self.anchors()]
        self.assertEqual(labels.count("Styled task"), 1)
        self.assertEqual(labels.count("Plain task"), 1)

    def test_the_page_controls_still_map(self):
        labels = [a["label"] for a in self.anchors()]
        self.assertIn("Add Element", labels)
        self.assertIn("New Todo Input", labels)

    def test_a_chosen_control_reports_itself_selected(self):
        """A component outline changes only a class, so the class is the evidence."""
        outline = next(a for a in self.anchors() if a["label"] == "TaskList")
        self.assertTrue(outline["selected"])
        self.assertFalse(next(a for a in self.anchors() if a["label"] == "Add Element")["selected"])


if __name__ == "__main__":
    unittest.main()
