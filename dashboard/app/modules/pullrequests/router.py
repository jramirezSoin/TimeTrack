"""Rutas del módulo de Pull Requests (HTMX: devuelven fragmentos HTML)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from .service import PullRequestsService

router = APIRouter()
service = PullRequestsService()


def _render(request: Request, plantilla: str, ctx: dict) -> HTMLResponse:
    # 200 a propósito: htmx no reemplaza el contenido con respuestas 4xx.
    return request.app.state.templates.TemplateResponse(request, f"pullrequests/{plantilla}", ctx)


def _mensaje(e: Exception) -> str:
    return str(e) or e.__class__.__name__


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    ctx = {"branches": [], "origen": "", "destino": "main", "error": None}
    try:  # Azure caído o sin configurar: la página abre igual y lo explica
        ctx["branches"] = service.branches()
        ctx["destino"] = service.destino_por_defecto()
        ctx["origen"] = service.origen_por_defecto()
    except Exception as e:
        ctx["error"] = _mensaje(e)
    return _render(request, "index.html", ctx)


@router.get("/mis", response_class=HTMLResponse)
def mis(request: Request):
    try:
        prs = service.mis_prs()
    except Exception as e:
        return _render(request, "_error.html", {"message": _mensaje(e)})
    return _render(request, "_mis.html", {"prs": prs})


@router.post("/estado", response_class=HTMLResponse)
def estado(request: Request, branch: str = Form(""), destino: str = Form("")):
    try:
        st = service.estado(branch, destino)
    except Exception as e:
        return _render(request, "_error.html", {"message": _mensaje(e)})
    return _render(request, "_estado.html", {"st": st})


@router.post("/crear", response_class=HTMLResponse)
def crear(request: Request, branch: str = Form(""), destino: str = Form(""), titulo: str = Form(""),
          descripcion: str = Form(""), draft: str = Form("")):
    try:
        pr = service.crear(branch, titulo, destino, descripcion, draft=bool(draft))
    except Exception as e:
        return _render(request, "_error.html", {"message": _mensaje(e)})
    return _render(request, "_resultado.html", {"pr": pr})
