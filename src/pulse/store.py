"""Atomic local persistence for maps and candidate routines."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .contracts import Routine, safe_id
from .screen_map import ScreenMap


def default_state_dir() -> Path:
    configured = os.environ.get("PULSE_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    shared_dev = Path.home() / "dev"
    if shared_dev.is_dir():
        return shared_dev / "pulse-data"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "pulse"


class Store:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else default_state_dir()

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / f"{safe_id(key)}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def load_map(self, app_id: str) -> ScreenMap | None:
        path = self._path("maps", app_id)
        if not path.exists():
            return None
        return ScreenMap.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_map(self, screen_map: ScreenMap) -> Path:
        path = self._path("maps", screen_map.app_id)
        self._atomic_write(path, screen_map.to_dict())
        return path

    def save_routine(self, raw: Mapping[str, Any]) -> Routine:
        routine = Routine.create(raw)
        self._atomic_write(self._path("routines", routine.id), routine.to_dict())
        return routine

    def load_routine(self, routine_id: str) -> dict[str, Any] | None:
        path = self._path("routines", routine_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_routines(self, app_id: str | None = None) -> list[dict[str, Any]]:
        directory = self.root / "routines"
        if not directory.exists():
            return []
        results = []
        for path in sorted(directory.glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            if app_id is None or item.get("app_id") == app_id:
                results.append({key: item[key] for key in ("id", "app_id", "name", "status", "version", "created_at")})
        return results
