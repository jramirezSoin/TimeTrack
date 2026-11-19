"""Plan neutral -> tareas de Azure DevOps (sin red).

- Con incidente: UNA Task hija "DEV - Revisión SOA" por (incidente, sprint), con las
  horas sumadas y las descripciones concatenadas por fecha.
- Fuera de incidente: UNA Task por sprint, "DEV - Joseph Ramirez", hija de
  "DEV - Tareas fuera de incidentes".

Cada tarea incluye `ref_keys`: claves de ledger de las actividades que cubre, y `ref_fechas`: la fecha
(ISO) de la tarea de cada una, en el mismo orden (el ledger la guarda para el calendario del historial).
"""
from __future__ import annotations

from typing import Callable

from ..ledger import activity_key
from ..models import Plan

TITULO_INCIDENTE = "DEV - Revisión SOA"
TITULO_AGRUPADA = "DEV - Joseph Ramirez"
TITULO_PADRE_FUERA = "DEV - Tareas fuera de incidentes"


def _horas(valor: float):
    valor = round(valor, 2)
    return int(valor) if valor == int(valor) else valor


def build_azure_tasks(plan: Plan, iteration_for: Callable) -> list[dict]:
    """iteration_for(fecha) -> path del sprint (p. ej. get_iteration_for)."""
    por_incidente: dict[tuple, dict] = {}
    agrupadas: dict[str, dict] = {}

    for dia in plan.dias:
        iteracion = iteration_for(dia.fecha)
        for act in dia.actividades:
            clave = activity_key("azure", dia.fecha, act)
            if act.incidente:
                g = por_incidente.setdefault((act.incidente, iteracion), {
                    "incident": act.incidente,
                    "title": TITULO_INCIDENTE,
                    "lines": [],
                    "hours": 0.0,
                    "iteration": iteracion,
                    "ref_keys": [],
                    "ref_fechas": [],
                })
                g["lines"].append(f"{dia.fecha:%d-%m-%Y}: {act.descripcion}")
                g["hours"] += act.horas
                g["ref_keys"].append(clave)
                g["ref_fechas"].append(dia.fecha.isoformat())
                continue
            grupo = agrupadas.setdefault(iteracion, {
                "parent_title": TITULO_PADRE_FUERA,
                "title": TITULO_AGRUPADA,
                "lines": [],
                "hours": 0.0,
                "iteration": iteracion,
                "ref_keys": [],
                "ref_fechas": [],
            })
            grupo["lines"].append(f"{dia.fecha:%d-%m-%Y}: {act.descripcion}")
            grupo["hours"] += act.horas
            grupo["ref_keys"].append(clave)
            grupo["ref_fechas"].append(dia.fecha.isoformat())

    tareas: list[dict] = []
    for g in por_incidente.values():
        tareas.append({
            "incident": g["incident"],
            "title": g["title"],
            "description": "<br>".join(g["lines"]),
            "hours": _horas(g["hours"]),
            "iteration": g["iteration"],
            "ref_keys": g["ref_keys"],
            "ref_fechas": g["ref_fechas"],
        })
    for grupo in agrupadas.values():
        tareas.append({
            "parent_title": grupo["parent_title"],
            "title": grupo["title"],
            "description": "<br>".join(grupo["lines"]),
            "hours": _horas(grupo["hours"]),
            "iteration": grupo["iteration"],
            "ref_keys": grupo["ref_keys"],
            "ref_fechas": grupo["ref_fechas"],
        })
    return tareas
