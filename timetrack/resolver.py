"""Resuelve un número de incidente a un work item de Azure.

Orden: catálogo local -> búsqueda en Azure -> crear el Bug (pidiendo el título).
"""
from __future__ import annotations

from typing import Callable, Protocol

from .catalog import Catalog


class Gateway(Protocol):
    def find_incident(self, incidente: str) -> int | None: ...
    def create_bug(self, titulo: str, iteration: str | None) -> int: ...


def resolve_incident(
    incidente: str,
    catalog: Catalog,
    gateway: Gateway,
    ask_title: Callable[[str], str],
    iteration: str | None = None,
) -> int:
    """Devuelve el id del work item del incidente, creándolo si no existe."""
    hit = catalog.get_incident(incidente)
    if hit:
        return hit["azure_id"]

    azure_id = gateway.find_incident(incidente)
    titulo = None
    if azure_id is None:
        titulo = (ask_title(incidente) or "").strip()
        if not titulo:
            raise ValueError(f"Se requiere un título para crear el Bug del incidente {incidente}.")
        # find_work_item busca por título, así que el número debe estar incluido.
        if incidente not in titulo:
            titulo = f"{incidente} - {titulo}"
        azure_id = gateway.create_bug(titulo, iteration)

    catalog.set_incident(incidente, azure_id, titulo)
    return azure_id
