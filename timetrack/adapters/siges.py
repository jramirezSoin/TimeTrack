"""Plan neutral -> tareas de SIGES (sin red). Una línea por actividad."""
from __future__ import annotations

import re
from typing import Callable

from ..ledger import day_key
from ..models import Plan

SIGES_TASK_ID = "1000000000112368"  # tarea fija


def numident_from_iteration(path: str) -> str:
    r"""'ST_Canales_CX\2026\Sprint 2026.22' -> 'SPR 22'."""
    m = re.search(r"\.(\d+)\s*$", path)
    if not m:
        raise ValueError(f"No se pudo derivar el numIdent de la iteración: {path!r}")
    return f"SPR {int(m.group(1))}"


def build_siges_days(plan: Plan, iteration_for: Callable) -> list[dict]:
    """Devuelve [{'fecha': 'YYYY-MM-DD', 'tareas': [...]}] listo para grabar_tareas."""
    dias = []
    for dia in plan.dias:
        numident = numident_from_iteration(iteration_for(dia.fecha))
        tareas = []
        for act in dia.actividades:
            comentario = f"{act.incidente} - {act.descripcion}" if act.incidente else act.descripcion
            tareas.append({
                "id": SIGES_TASK_ID,
                "incident": act.incidente or "",
                "horas": float(act.horas),
                "comentario": comentario,
                "numIdent": numident,
                "clienteId": "null",
                "subClienteCod": "null",
                "especialidadId": "null",
                "avanceNuevo": 0,
            })
        dias.append({
            "fecha": dia.fecha.isoformat(),
            "tareas": tareas,
            "ref_key": day_key("siges", dia),
        })
    return dias
