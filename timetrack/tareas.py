"""Tareas personales de la semana (solo locales): pendiente -> en proceso -> entregada -> cerrada.

Si una tarea indica un incidente, se vincula con su Bug padre de Azure reutilizando
`resolve_incident` (catálogo -> Azure -> crear el Bug). La red se inyecta, igual que en el pipeline.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, field_validator

from .catalog import Catalog
from .ledger import write_json_atomic
from .resolver import Gateway, resolve_incident

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "tareas.json"
_SEMANA_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


class Estado(str, Enum):
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    ENTREGADA = "entregada"
    CERRADA = "cerrada"


def semana_de(fecha: date | None = None) -> str:
    """Semana ISO de una fecha (hoy por defecto), p. ej. '2026-W45'."""
    anio, semana, _ = (fecha or date.today()).isocalendar()
    return f"{anio}-W{semana:02d}"


def _validar_semana(v: str) -> str:
    v = v.strip().upper()
    if not _SEMANA_RE.match(v):
        raise ValueError(f"Semana inválida '{v}': use el formato AAAA-Wnn (p. ej. 2026-W45).")
    return v


def _validar_titulo(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("El título no puede estar vacío.")
    return v


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Tarea(BaseModel):
    id: int
    titulo: str = Field(min_length=1)
    estado: Estado = Estado.PENDIENTE
    incidente: str | None = None
    azure_id: int | None = None          # Bug padre en Azure, si hay incidente
    semana: str
    notas: str = ""
    creada: str
    actualizada: str

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, v: str) -> str:
        return _validar_titulo(v)

    @field_validator("incidente", mode="before")
    @classmethod
    def _incidente(cls, v):
        if v is None:
            return None
        return str(v).strip() or None

    @field_validator("semana")
    @classmethod
    def _semana(cls, v: str) -> str:
        return _validar_semana(v)


class TareaError(Exception):
    """Error de uso (id inexistente, archivo corrupto...), pensado para mostrarse tal cual."""


class TaskStore:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self._siguiente = 1
        self._tareas: list[Tarea] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._tareas = [Tarea.model_validate(t) for t in data.get("tareas", [])]
                self._siguiente = int(data.get("siguiente_id", 1))
            except (ValueError, TypeError, AttributeError) as e:  # JSONDecodeError y ValidationError son ValueError
                # No se descarta en silencio: sobrescribirlo perdería las tareas.
                raise TareaError(
                    f"El archivo de tareas {self.path} está corrupto ({e}). "
                    "Restáurelo o corríjalo a mano; no se modificó."
                ) from e
            # El contador nunca puede quedar por debajo de un id existente.
            self._siguiente = max([self._siguiente, *(t.id + 1 for t in self._tareas)])

    # --- lectura ---
    def obtener(self, id: int) -> Tarea:
        for t in self._tareas:
            if t.id == id:
                return t
        raise TareaError(f"No existe la tarea {id}.")

    def listar(self, semana: str | None = None, estado: Estado | None = None) -> list[Tarea]:
        if semana is not None:
            semana = _validar_semana(semana)
        return [
            t.model_copy() for t in self._tareas
            if (semana is None or t.semana == semana) and (estado is None or t.estado == estado)
        ]

    def resumen(self, semana: str | None = None) -> dict[Estado, int]:
        """Conteo por estado (todos los estados aparecen, aunque sea con 0)."""
        conteo = {e: 0 for e in Estado}
        for t in self.listar(semana=semana):
            conteo[t.estado] += 1
        return conteo

    # --- escritura ---
    def crear(
        self,
        titulo: str,
        incidente: str | None = None,
        semana: str | None = None,
        notas: str = "",
        *,
        catalog: Catalog | None = None,
        gateway: Gateway | None = None,
        ask_title: Callable[[str], str] | None = None,
        iteration: str | None = None,
    ) -> Tarea:
        """Crea la tarea. Con incidente resuelve (o crea, con el título de la tarea) su Bug padre antes de guardar."""
        ahora = _ahora()
        tarea = Tarea(
            id=self._siguiente, titulo=titulo, incidente=incidente, notas=notas,
            semana=semana or semana_de(), creada=ahora, actualizada=ahora,
        )
        if tarea.incidente:
            if catalog is None or gateway is None:
                raise TareaError("Para vincular un incidente se requiere catálogo y gateway.")
            # Incidente nuevo: el Bug se crea con el título de la tarea (salvo que se pase otro ask_title).
            # Si Azure falla, esto lanza y la tarea no se guarda a medias.
            tarea.azure_id = resolve_incident(
                tarea.incidente, catalog, gateway, ask_title or (lambda _inc: tarea.titulo), iteration)
        self._tareas.append(tarea)
        self._siguiente += 1
        self._guardar()
        return tarea.model_copy()

    def mover(self, id: int, estado: Estado) -> Tarea:
        t = self.obtener(id)
        t.estado = Estado(estado)
        t.actualizada = _ahora()
        self._guardar()
        return t.model_copy()

    def editar(self, id: int, *, titulo: str | None = None, semana: str | None = None,
               notas: str | None = None) -> Tarea:
        t = self.obtener(id)
        if titulo is not None:
            t.titulo = _validar_titulo(titulo)
        if semana is not None:
            t.semana = _validar_semana(semana)
        if notas is not None:
            t.notas = notas
        t.actualizada = _ahora()
        self._guardar()
        return t.model_copy()

    def eliminar(self, id: int) -> None:
        self._tareas.remove(self.obtener(id))
        self._guardar()

    def _guardar(self) -> None:
        write_json_atomic(self.path, {
            "siguiente_id": self._siguiente,
            "tareas": [t.model_dump(mode="json") for t in self._tareas],
        })
