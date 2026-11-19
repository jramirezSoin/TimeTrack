"""Registro de lo ya enviado, para no duplicar al reintentar.

- Azure: una clave por actividad.
- SIGES: una clave por día completo (no se reenvían tareas sueltas de un día).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from .models import Actividad, Dia, Plan

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "ledger.json"


def write_json_atomic(path: Path, data) -> None:
    """Escribe a un temporal y reemplaza, para que una interrupción no deje el archivo vacío."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _hash(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()


def _act_repr(a: Actividad) -> str:
    return f"{a.incidente or ''}|{a.descripcion}|{round(a.horas, 2)}"


def activity_key(sistema: str, fecha, act: Actividad) -> str:
    return _hash(sistema, fecha.isoformat(), _act_repr(act))


def day_key(sistema: str, dia: Dia) -> str:
    return _hash(sistema, dia.fecha.isoformat(), *[_act_repr(a) for a in dia.actividades])


class Ledger:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self._data = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                # No se descarta en silencio: reenviar sin ledger podría duplicar horas.
                raise RuntimeError(
                    f"El ledger {self.path} está vacío o corrupto ({e}). Verifique en Azure y "
                    "SIGES qué se envió; luego restaure el archivo o elimínelo a conciencia."
                ) from e

    def has(self, key: str) -> bool:
        return key in self._data

    def entries(self) -> dict:
        """Copia de solo lectura de lo registrado (clave -> metadatos)."""
        return {k: dict(v) for k, v in self._data.items()}

    def add(self, key: str, **meta) -> None:
        self._data[key] = {"enviado": datetime.now().isoformat(timespec="seconds"), **meta}
        write_json_atomic(self.path, self._data)


def pending_activities(plan: Plan, sistema: str, ledger: Ledger) -> Plan | None:
    """Plan con solo las actividades aún no enviadas a `sistema` (None si no queda ninguna)."""
    dias = []
    for dia in plan.dias:
        acts = [a for a in dia.actividades if not ledger.has(activity_key(sistema, dia.fecha, a))]
        if acts:
            dias.append(Dia(fecha=dia.fecha, actividades=acts))
    return Plan(dias=dias) if dias else None


def pending_days(plan: Plan, sistema: str, ledger: Ledger) -> Plan | None:
    """Plan con solo los días completos aún no enviados a `sistema`."""
    dias = [d for d in plan.dias if not ledger.has(day_key(sistema, d))]
    return Plan(dias=dias) if dias else None
