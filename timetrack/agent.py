"""Agente: convierte la prosa del usuario en un Plan (vía API de Claude).

Claude solo EXTRAE (fecha tal como aparece, descripción literal, horas, incidente).
El código convierte las fechas, exige las horas y construye el Plan validado, de modo
que el modelo no decide fechas ni inventa horas.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime

from pydantic import BaseModel, ValidationError

from .models import Actividad, Dia, Plan

MODEL = os.environ.get("TIMETRACK_MODEL", "claude-haiku-5-5")

SYSTEM_PROMPT = """\
Extraes actividades de un reporte de horas escrito en prosa (español). El texto agrupa \
actividades por fecha; una línea con solo una fecha (p. ej. 29-10-2026) abre un día nuevo.

Para cada actividad devuelve:
- descripcion: el texto de la actividad, copiado literalmente. Sin el número de incidente \
del inicio, sin las horas del final y sin la marca "Fuera de incidente". No resumas ni \
reescribas ni corrijas.
- incidente: el número de incidente o la HU si la actividad empieza con uno (p. ej. 100001273  ej. HU217174). \
Si empieza con "Fuera de incidente" o no trae número, poner 'DEV - Tareas fuera de incidentes'.
- horas: las horas indicadas para esa actividad (normalmente un número al final de la \
línea). Si no están escritas, null. Nunca calcules, repartas ni estimes horas.

Para fecha copia el texto de la fecha exactamente como aparece. Conserva el orden del texto. \
Una actividad puede ocupar varias líneas; no inventes actividades que no estén en el texto.
"""


class ActividadExt(BaseModel):
    descripcion: str
    incidente: str | None
    horas: float | None


class DiaExt(BaseModel):
    fecha: str
    actividades: list[ActividadExt]


class Extraccion(BaseModel):
    dias: list[DiaExt]


class ExtraccionError(ValueError):
    """La prosa no pudo convertirse en un plan válido; el mensaje lista los problemas."""


def _parse_fecha(texto: str):
    texto = texto.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"fecha no reconocida: {texto!r}")


def to_plan(ext: Extraccion) -> Plan:
    """Convierte la extracción en Plan, exigiendo fechas válidas y horas explícitas."""
    problemas: list[str] = []
    dias: list[Dia] = []
    for d in ext.dias:
        try:
            fecha = _parse_fecha(d.fecha)
        except ValueError as e:
            problemas.append(str(e))
            continue
        acts = []
        for a in d.actividades:
            resumen = a.descripcion[:50]
            if a.horas is None or a.horas <= 0:
                problemas.append(f"{d.fecha}: sin horas válidas en «{resumen}…»")
                continue
            acts.append(Actividad(descripcion=a.descripcion, horas=a.horas, incidente=a.incidente))
        if acts:
            dias.append(Dia(fecha=fecha, actividades=acts))
        elif not any(p.startswith(d.fecha) for p in problemas):
            problemas.append(f"{d.fecha}: el día no trae actividades")
    if problemas:
        raise ExtraccionError("La prosa no es válida:\n  - " + "\n  - ".join(problemas))
    if not dias:
        raise ExtraccionError("No se encontró ningún día con actividades en el texto.")
    return Plan(dias=dias)


class _Heartbeat:
    """Muestra que el agente sigue trabajando: contador de segundos mientras espera."""

    FRAMES = "|/-\\"

    def __init__(self, mensaje: str, stream=None):
        self.mensaje = mensaje
        self.stream = stream or sys.stderr
        self.tty = self.stream.isatty()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._t0 = 0.0

    def _run(self):
        n = 0
        # En terminal se redibuja cada 0.25 s; en archivo/pipe, una línea cada 5 s.
        intervalo = 0.25 if self.tty else 5.0
        while not self._stop.wait(intervalo):
            n += 1
            s = int(time.monotonic() - self._t0)
            if self.tty:
                self.stream.write(f"\r  {self.FRAMES[n % 4]} {self.mensaje} {s}s ")
            else:
                self.stream.write(f"  ... {self.mensaje} {s}s\n")
            self.stream.flush()

    def __enter__(self):
        self._t0 = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        if self.tty:
            self.stream.write("\r" + " " * 70 + "\r")
            self.stream.flush()
        self.segundos = time.monotonic() - self._t0
        return False


def parse_prose(
    texto: str, client=None, model: str | None = None, verbose: bool = False,
    progress=None,
) -> Plan:
    """Prosa -> Plan. `client` es un anthropic.Anthropic (o un doble en tests).

    verbose=True muestra el avance por etapas y un contador mientras Claude responde.
    progress: callback(str) para recibir esas etapas (p. ej. el dashboard web); si se
    pasa, reemplaza la salida por consola y no se dibuja el contador.
    """
    def say(msg: str):
        if progress is not None:
            progress(msg.strip())
        elif verbose:
            print(msg, file=sys.stderr, flush=True)

    if not texto.strip():
        raise ExtraccionError("El texto está vacío.")
    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    modelo = model or MODEL
    lineas = len([l for l in texto.splitlines() if l.strip()])
    say(f"[agente] Enviando {lineas} línea(s) a {modelo}...")

    def llamar():
        return client.messages.parse(
            model=modelo,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": texto}],
            output_format=Extraccion,
        )

    if verbose or progress is not None:
        t0 = time.monotonic()
        if progress is None:
            with _Heartbeat("[agente] Claude está leyendo e interpretando el reporte...") as hb:
                response = llamar()
            segundos = hb.segundos
        else:
            response = llamar()
            segundos = time.monotonic() - t0
        usage = getattr(response, "usage", None)
        tokens = f" ({usage.input_tokens} tokens de entrada, {usage.output_tokens} de salida)" if usage else ""
        say(f"[agente] Respuesta recibida en {segundos:.1f}s{tokens}.")
    else:
        response = llamar()

    if response.stop_reason == "refusal":
        raise ExtraccionError("El modelo rechazó procesar el texto (stop_reason=refusal).")
    if response.stop_reason == "max_tokens":
        raise ExtraccionError("La respuesta se truncó (max_tokens); divida el texto en partes.")
    ext = response.parsed_output
    if ext is None:
        raise ExtraccionError("El modelo no devolvió una extracción válida.")
    say("[agente] Validando fechas y horas...")
    plan = to_plan(ext)
    acts = sum(len(d.actividades) for d in plan.dias)
    say(f"[agente] Listo: {len(plan.dias)} día(s), {acts} actividad(es) interpretadas.\n")
    return plan
