"""Catálogo local (caché) de incidentes ya resueltos: número -> work item de Azure."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


class Catalog:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self._data = {"incidentes": {}}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            self._data.setdefault("incidentes", {})

    def get_incident(self, incidente: str) -> dict | None:
        return self._data["incidentes"].get(str(incidente))

    def incidents(self) -> dict:
        """Copia de solo lectura de los incidentes conocidos."""
        return {k: dict(v) for k, v in self._data["incidentes"].items()}

    def set_incident(self, incidente: str, azure_id: int, titulo: str | None = None) -> None:
        self._data["incidentes"][str(incidente)] = {"azure_id": azure_id, "titulo": titulo}
        self.save()

    def save(self) -> None:
        from .ledger import write_json_atomic
        write_json_atomic(self.path, self._data)
