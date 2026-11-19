"""Validaciones deterministas del plan (no dependen del LLM)."""
from __future__ import annotations

from .models import Plan

HORAS_POR_DIA = 8.0


class PlanError(ValueError):
    """El plan no cumple las reglas; el mensaje lista todos los problemas."""


def validate_plan(plan: Plan, horas_dia: float = HORAS_POR_DIA) -> None:
    problemas = []
    vistas = set()
    for dia in plan.dias:
        if dia.fecha in vistas:
            problemas.append(f"{dia.fecha:%d-%m-%Y}: fecha repetida en la prosa")
        vistas.add(dia.fecha)
        if abs(dia.total_horas - horas_dia) > 1e-6:
            problemas.append(
                f"{dia.fecha:%d-%m-%Y}: suma {dia.total_horas} h, se esperaban {horas_dia} h"
            )
    if problemas:
        raise PlanError("Plan inválido:\n  - " + "\n  - ".join(problemas))
