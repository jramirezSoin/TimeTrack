"""Modelo intermedio neutral: lo que produce el agente y consumen los adaptadores."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class Actividad(BaseModel):
    descripcion: str = Field(min_length=1)
    horas: float = Field(gt=0)
    # Número de incidente (ej. "100001273"). None = "Fuera de incidente".
    incidente: str | None = None

    @field_validator("incidente", mode="before")
    @classmethod
    def _limpiar_incidente(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None


class Dia(BaseModel):
    fecha: date
    actividades: list[Actividad] = Field(min_length=1)

    @property
    def total_horas(self) -> float:
        return round(sum(a.horas for a in self.actividades), 2)


class Plan(BaseModel):
    dias: list[Dia] = Field(min_length=1)
