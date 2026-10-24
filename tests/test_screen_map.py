from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pulse.contracts import Routine
from pulse.contracts import ScreenState
from pulse.screen_map import ScreenMap
from pulse.store import Store


def screen(title: str, anchors: list[dict]) -> dict:
    return {"url": f"https://example.test/{title.lower()}", "title": title,
            "viewport": {"width": 1280, "height": 800}, "anchors": anchors}


def anchor(anchor_id: str, label: str, x: float, y: float, *, action=False, effect="read") -> dict:
    return {"id": anchor_id, "role": "link" if action else "heading", "label": label,
            "bounds": {"x": x, "y": y, "width": 0.1, "height": 0.05},
            "actionable": action, "effect": effect}


class ScreenMapTests(unittest.TestCase):
    def test_grid_and_shortest_verified_route(self):
        site = ScreenMap.create("erp", columns=8, rows=12)
        home = site.add_screen(screen("Home", [anchor("invoices", "Invoices", .80, .10, action=True)]))
        invoices = site.add_screen(screen("Invoices", [anchor("heading", "Invoice list", .1, .1)]))
        site.add_transition({"source": home.id, "anchor_id": "invoices", "target": invoices.id,
                             "label": "Invoices", "verified": False})
        self.assertIsNone(site.route(home.id, "Invoice list"))
        site.add_transition({"source": home.id, "anchor_id": "invoices", "target": invoices.id,
                             "label": "Invoices", "verified": True})
        route = site.route(home.id, "Invoice list")
        self.assertEqual(route["transition_count"], 1)
        self.assertEqual(route["steps"][0]["anchor_id"], "invoices")
        grid = site.grid(home.id)
        self.assertEqual(grid[1][6][0]["label"], "Invoices")

    def test_invalid_or_unsafe_anchors_are_rejected(self):
        site = ScreenMap.create("erp")
        with self.assertRaises(ValueError):
            site.add_screen(screen("Bad", [anchor("bad", "Off screen", .95, .1)]))
        with self.assertRaises(ValueError):
            site.add_screen(screen("Bad", [{**anchor("bad", "Submit", .1, .1, action=True),
                                              "effect": "secret"}]))

    def test_map_round_trip_and_candidate_routine_storage(self):
        site = ScreenMap.create("erp")
        first = site.add_screen(screen("Home", [anchor("go", "Invoices", .2, .1, action=True)]))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.save_map(site)
            restored = store.load_map("erp")
            self.assertEqual(restored.screens[first.id].title, "Home")
            routine = store.save_routine({
                "id": "open-invoices", "app_id": "erp", "name": "Open invoices",
                "steps": [{"anchor_id": "go", "operation": "click", "expected_state": "invoice-list"}],
                "final_state": "invoice-list", "evidence": "Invoice list heading observed",
            })
            self.assertEqual(routine.status, "candidate")
            self.assertEqual(store.list_routines("erp")[0]["id"], "open-invoices")
            self.assertEqual(store.load_routine("open-invoices")["status"], "candidate")
            self.assertEqual(Path(tmp, "maps", "erp.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(tmp, "maps").stat().st_mode & 0o777, 0o700)

    def test_routine_cannot_be_saved_without_verification_evidence(self):
        raw = {"id": "routine", "app_id": "erp", "name": "Do work",
               "steps": [{"anchor_id": "save", "operation": "click", "expected_state": "done"}],
               "final_state": "done"}
        with self.assertRaisesRegex(ValueError, "evidence"):
            Routine.create(raw)
        raw["evidence"] = "confirmation heading visible"
        raw["status"] = "approved"
        with self.assertRaisesRegex(ValueError, "candidates"):
            Routine.create(raw)
        raw["status"] = "candidate"
        raw["steps"][0]["value"] = "do-not-persist-secret"
        with self.assertRaisesRegex(ValueError, "literal values"):
            Routine.create(raw)

    def test_url_identity_drops_query_and_fragment_secrets(self):
        state = ScreenState.create({
            "app_id": "erp", "url": "https://example.test/home?token=secret#/private",
            "title": "Home", "viewport": {"width": 100, "height": 100},
            "anchors": [anchor("home", "Home", .1, .1)],
        })
        self.assertEqual(state.url, "https://example.test/home")
        self.assertNotIn("secret", str(state.to_dict()))


if __name__ == "__main__":
    unittest.main()
