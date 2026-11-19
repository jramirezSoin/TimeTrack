"""Rutas del módulo de horas (HTMX: devuelven fragmentos HTML)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...jobs import JobStore
from .service import HorasService

router = APIRouter()
service = HorasService()
jobs = JobStore()


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, name, ctx)


def _error(request: Request, message: str) -> HTMLResponse:
    # 200 a propósito: htmx no reemplaza el contenido con respuestas 4xx.
    return render(request, "horas/_error.html", message=message, log=[])


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "horas/index.html")


@router.post("/interpretar", response_class=HTMLResponse)
def interpretar(request: Request, prosa: str = Form("")):
    if not prosa.strip():
        return _error(request, "Pegue el reporte antes de interpretarlo.")
    job = jobs.start("interpretar", lambda j: service.interpretar(j, prosa))
    return render(request, "horas/_job.html", job=job, log=job.snapshot())


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_status(request: Request, job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return _error(request, "La tarea ya no existe. Interprete el reporte de nuevo.")
    log = job.snapshot()
    if job.status == "running":
        return render(request, "horas/_job.html", job=job, log=log)
    if job.status == "error":
        return render(request, "horas/_error.html", message=job.error, log=log)
    if job.kind == "interpretar":
        preview = service.get_preview(job.result)
        if preview is None:
            return _error(request, "La vista previa expiró. Interprete el reporte de nuevo.")
        return render(request, "horas/_preview.html", preview=preview, preview_id=job.result, log=log)
    # kind == "enviar"
    result = job.result
    azure = [{**a, "url": service.workitem_url(a["ref"])} for a in result.azure]
    return render(request, "horas/_result.html", result=result, azure=azure, log=log)


@router.post("/enviar", response_class=HTMLResponse)
async def enviar(request: Request):
    form = await request.form()
    pid = str(form.get("preview_id", ""))
    preview = service.get_preview(pid)
    if preview is None:
        return _error(request, "La vista previa no existe o ya se envió. Interprete el reporte de nuevo.")

    titles = {inc: str(form.get(f"titulo__{inc}", "")).strip() for inc in preview.new_incidents}
    faltan = [inc for inc, t in titles.items() if not t]
    if faltan:
        return _error(request, "Falta el título del Bug para: " + ", ".join(faltan))

    preview = service.take_preview(pid)  # se consume: no se puede enviar dos veces
    if preview is None:
        return _error(request, "Esta vista previa ya se está enviando.")
    job = jobs.start("enviar", lambda j: service.enviar(j, preview, titles))
    return render(request, "horas/_job.html", job=job, log=job.snapshot())


@router.get("/sprint", response_class=HTMLResponse)
def sprint(request: Request):
    return render(request, "horas/sprint.html")


@router.get("/sprint/tareas", response_class=HTMLResponse)
def sprint_tareas(request: Request, numero: str = ""):
    """Consulta de solo lectura; los errores (sprint inexistente, Azure caído) se muestran en el fragmento."""
    if not numero.strip():
        return render(request, "horas/_sprint.html", error="Escriba el número del sprint (por ejemplo 22).")
    try:
        datos = service.sprint(numero)
    except Exception as e:
        return render(request, "horas/_sprint.html", error=str(e) or e.__class__.__name__)
    return render(request, "horas/_sprint.html", **datos)


@router.get("/historial", response_class=HTMLResponse)
def historial(request: Request, mes: str | None = None, dia: str | None = None):
    return render(request, "horas/historial.html", **service.historial(mes=mes, dia=dia))
