"""Rutas del módulo de tareas (HTMX: devuelven el fragmento del tablero)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from timetrack.tareas import Estado, TareaError

from .service import TareasService

router = APIRouter()
service = TareasService()

COLUMNAS = [
    (Estado.PENDIENTE, "Pendientes", "bi-inbox"),
    (Estado.EN_PROCESO, "En proceso", "bi-pencil"),
    (Estado.ENTREGADA, "Entregadas", "bi-send-check"),
]


def _tablero(request: Request, error: str | None = None) -> HTMLResponse:
    # 200 a propósito: htmx no reemplaza el contenido con respuestas 4xx.
    return request.app.state.templates.TemplateResponse(
        request, "tareas/_board.html",
        {"tablero": service.tablero(), "columnas": COLUMNAS, "error": error},
    )


def _mensaje(e: Exception) -> str:
    return str(e) or e.__class__.__name__


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return request.app.state.templates.TemplateResponse(
        request, "tareas/index.html",
        {"tablero": service.tablero(), "columnas": COLUMNAS, "error": None},
    )


@router.post("/nueva", response_class=HTMLResponse)
def nueva(request: Request, titulo: str = Form(""), incidente: str = Form("")):
    if not titulo.strip():
        return _tablero(request, "Escriba el título de la tarea.")
    try:
        service.nueva(titulo, incidente)
    except Exception as e:  # Azure caído, título inválido...: se muestra, no se guarda nada
        return _tablero(request, _mensaje(e))
    return _tablero(request)


@router.post("/{tarea_id}/mover", response_class=HTMLResponse)
def mover(request: Request, tarea_id: int, estado: str = Form("")):
    try:
        service.mover(tarea_id, estado)
    except TareaError as e:
        return _tablero(request, _mensaje(e))
    return _tablero(request)
