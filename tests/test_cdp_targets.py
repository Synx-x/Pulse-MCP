"""Tab selection must follow the page under test, not whichever tab opened last.

A second page target on one CDP port once made an agent observe a leftover
"Fixture" tab. The URL it read did not match the site in its goal, so it refused
the task. Pinning a target URL fixes that, and this file holds the rule.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pulse.drivers.cdp import CdpError, page_targets  # noqa: E402


def target(url: str, kind: str = "page") -> dict:
    return {"type": kind, "url": url, "webSocketDebuggerUrl": f"ws://{url}"}


class PageTargetTests(unittest.TestCase):
    """The first page target must be the one the caller named."""

    def choose(self, targets: list[dict], target_url: str = "") -> list[dict]:
        body = __import__("json").dumps(targets).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return body

        with patch("pulse.drivers.cdp.urllib.request.urlopen", return_value=Response()):
            return page_targets(9222, target_url)

    def test_a_named_page_is_chosen_over_a_newer_one(self):
        pages = self.choose([target("https://elsewhere.test/"),
                             target("https://example.test/list")], "https://example.test")
        self.assertEqual(pages[0]["url"], "https://example.test/list")

    def test_an_unnamed_page_still_avoids_a_browser_surface(self):
        pages = self.choose([target("chrome://omnibox-popup.top-chrome/", "browser_ui"),
                             target("about:blank")])
        self.assertEqual(pages[0]["url"], "about:blank")

    def test_no_page_target_reports_the_port(self):
        with self.assertRaises(CdpError):
            self.choose([target("chrome://omnibox-popup.top-chrome/", "browser_ui")])


if __name__ == "__main__":
    unittest.main()
