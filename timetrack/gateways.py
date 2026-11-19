"""Gateways reales hacia Azure DevOps y SIGES (importación perezosa de los servicios)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .sprint import agrupar_por_padre, elegir_iteracion, parse_sprint, totales

_ROOT = Path(__file__).resolve().parent.parent
_AZURE_DIR = _ROOT / "azure"
_SIGES_DIR = _ROOT / "siges"


def _load(directory: Path, module: str):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return __import__(module)


class AzureGateway:
    def __init__(self):
        self._svc = _load(_AZURE_DIR, "azure_devops_service")

    def iteration_for(self, fecha) -> str:
        return self._svc.get_iteration_for(fecha)

    def workitem_url(self, work_item_id) -> str:
        return f"{self._svc.AZURE_ENDPOINT}/_workitems/edit/{work_item_id}"

    def find_incident(self, incidente: str) -> int | None:
        ids = self._svc.find_work_item(incidente, quiet=True)
        return ids[0] if ids else None

    def create_bug(self, titulo: str, iteration: str | None) -> int:
        # Valores por defecto (assignedTo, campos requeridos) salen de parent_task.json.
        base = json.loads((_AZURE_DIR / "parent_task.json").read_text(encoding="utf-8"))["parent"]
        return self._svc.create_parent_task({**base, "title": titulo, "iteration": iteration})

    def sprint_tasks(self, sprint) -> dict:
        """Mis Tasks de un sprint (número, o año.número) agrupadas por su padre, con horas y estado."""
        anio, numero = parse_sprint(sprint)
        it = elegir_iteracion(self._svc.get_iterations(), anio, numero)
        raw = self._svc.get_my_sprint(it["path"])
        grupos = agrupar_por_padre(raw["items"], raw["parents"])
        return {"sprint": it["name"], "grupos": grupos, "totales": totales(grupos)}

    def upsert_child(self, parent_id: int, task: dict):
        return self._svc.upsert_child_task(parent_id, task)

    def upsert_grouped(self, task: dict):
        return self._svc.upsert_grouped_task(task)


class AzureReposGateway:
    """Commits pendientes y Pull Requests del repo configurado en azure/config.json ("repos")."""

    def __init__(self):
        self._svc = _load(_AZURE_DIR, "azure_repos_service")

    def default_target(self) -> str:
        return self._svc.default_target()

    def default_source(self) -> str:
        return self._svc.default_source()

    def branches(self, repo: str | None = None) -> list[str]:
        return self._svc.list_branches(repo)

    def status(self, source: str, target: str | None = None, repo: str | None = None) -> dict:
        return self._svc.commits_status(source, target, repo)

    def active_pr(self, source: str, target: str | None = None, repo: str | None = None):
        return self._svc.find_active_pr(source, target, repo)

    def my_active_prs(self, repo: str | None = None) -> list[dict]:
        return self._svc.list_my_active_prs(repo)

    def create_pr(self, source: str, title: str, target: str | None = None, description: str = "",
                  repo: str | None = None, draft: bool = False) -> dict:
        return self._svc.create_pull_request(source, title, target=target, description=description,
                                             repo=repo, draft=draft)


class SigesGateway:
    def __init__(self):
        self._svc = _load(_SIGES_DIR, "siges_service")

    def send_day(self, fecha: str, tareas: list[dict], cerrar_dia: bool = False):
        return self._svc.grabar_tareas(tareas, fecha=fecha, cerrar_dia=cerrar_dia)
