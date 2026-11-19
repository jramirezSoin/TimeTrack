"""Rutas del módulo de utilidades (HTMX: devuelven fragmentos HTML). Cada herramienta se describe con un dict."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...jobs import JobStore
from . import agente, herramientas as h

router = APIRouter()
jobs = JobStore()


# ───────────── manejadores: reciben el formulario (dict) y devuelven el contexto del resultado ─────────────
def _json(f: dict) -> dict:
    accion = f.get("accion") or "formatear"
    if accion == "comparar":
        return {"diffs": h.json_comparar(f.get("texto", ""), f.get("texto2", ""))}
    return {"bloques": [("Resultado", h.json_formatear(f.get("texto", ""), minificar=accion == "minificar"))]}


def _xml(f: dict) -> dict:
    accion = f.get("accion") or "formatear"
    if accion == "comparar":
        return {"diffs": h.xml_comparar(f.get("texto", ""), f.get("texto2", ""))}
    return {"bloques": [("Resultado", h.xml_formatear(f.get("texto", ""), minificar=accion == "minificar"))]}


def _base64(f: dict) -> dict:
    urlsafe = bool(f.get("urlsafe"))
    if (f.get("accion") or "codificar") == "decodificar":
        r = h.b64_decodificar(f.get("texto", ""), urlsafe)
        ctx = {"bloques": [("Texto", r["texto"])], "filas": [("Bytes", str(r["bytes"]))]}
        if not r["utf8"]:
            ctx["avisos"] = ["El resultado no es texto UTF-8 válido (probablemente datos binarios); se muestra con "
                             "caracteres de reemplazo."]
            ctx["filas"].append(("Primeros bytes (hex)", r["hex"]))
        return ctx
    return {"bloques": [("Base64", h.b64_codificar(f.get("texto", ""), urlsafe))]}


def _jwt(f: dict) -> dict:
    r = h.jwt_decodificar(f.get("texto", ""))
    filas = list(r["fechas"])
    if r["expirado"] is True:
        filas.append(("Estado", "EXPIRADO"))
    elif r["aun_no_valido"]:
        filas.append(("Estado", "Aún no es válido (nbf en el futuro)"))
    elif r["expirado"] is False:
        filas.append(("Estado", "Vigente"))
    else:
        filas.append(("Estado", "Sin fecha de expiración (exp)"))
    avisos = ["No se verifica la firma: el contenido se muestra tal cual viene, sin garantía de autenticidad."]
    if not r["firma"]:
        avisos.append("El token no trae firma (tercera parte vacía).")
    return {"bloques": [("Encabezado", json.dumps(r["encabezado"], ensure_ascii=False, indent=2)),
                        ("Payload", json.dumps(r["payload"], ensure_ascii=False, indent=2))],
            "filas": filas, "avisos": avisos}


def _timestamp(f: dict) -> dict:
    if (f.get("accion") or "a_fecha") == "a_timestamp":
        return {"filas": h.fecha_a_timestamp(f.get("fecha", ""), f.get("zona") or h.ZONA_LOCAL)}
    return {"filas": h.timestamp_a_fecha(f.get("timestamp", ""), f.get("unidad") or "auto")}


def _fechas(f: dict) -> dict:
    return {"filas": h.fecha_convertir(f.get("fecha", ""), f.get("origen") or h.ZONA_LOCAL, f.get("destino") or "UTC")}


def _ta(name, label, rows=8, placeholder="", ayuda=""):
    return {"name": name, "label": label, "tipo": "textarea", "rows": rows, "placeholder": placeholder, "ayuda": ayuda}


def _tx(name, label, placeholder="", valor="", lista=None, ahora=False, ancho=""):
    return {"name": name, "label": label, "tipo": "text", "placeholder": placeholder, "valor": valor,
            "lista": lista, "ahora": ahora, "ancho": ancho}


HERRAMIENTAS = [
    {"slug": "json", "titulo": "JSON", "icono": "bi-braces", "manejador": _json,
     "descripcion": "Formatee, minifique, valide y compare JSON. La comparación ignora el orden de las claves.",
     "campos": [_ta("texto", "JSON", 12, '{"a": 1}'), _ta("texto2", "Segundo JSON (solo para comparar)", 6)],
     "acciones": [("formatear", "Formatear", "bi-text-indent-left"), ("minificar", "Minificar", "bi-arrows-collapse"),
                  ("comparar", "Comparar", "bi-subtract")]},
    {"slug": "xml", "titulo": "XML", "icono": "bi-code-slash", "manejador": _xml,
     "descripcion": "Formatee, minifique, valide y compare XML. No se aceptan DTD ni entidades, por seguridad.",
     "campos": [_ta("texto", "XML", 12, "<a><b>1</b></a>"), _ta("texto2", "Segundo XML (solo para comparar)", 6)],
     "acciones": [("formatear", "Formatear", "bi-text-indent-left"), ("minificar", "Minificar", "bi-arrows-collapse"),
                  ("comparar", "Comparar", "bi-subtract")]},
    {"slug": "base64", "titulo": "Base64", "icono": "bi-file-earmark-binary", "manejador": _base64,
     "descripcion": "Codifique o decodifique texto (UTF-8) en Base64.",
     "campos": [_ta("texto", "Texto", 8), {"name": "urlsafe", "label": "Variante URL-safe (- y _)", "tipo": "check"}],
     "acciones": [("codificar", "Codificar", "bi-lock"), ("decodificar", "Decodificar", "bi-unlock")]},
    {"slug": "jwt", "titulo": "JWT", "icono": "bi-key", "manejador": _jwt,
     "descripcion": "Decodifique encabezado y payload de un JWT y vea si ya expiró. No verifica la firma.",
     "campos": [_ta("texto", "Token", 6, "eyJhbGciOi…", "Puede pegarlo con o sin el prefijo «Bearer».")],
     "acciones": [("decodificar", "Decodificar", "bi-unlock")]},
    {"slug": "timestamp", "titulo": "Timestamp", "icono": "bi-hourglass-split", "manejador": _timestamp,
     "descripcion": "Convierta un Unix timestamp a fecha y viceversa. Con «automática», valores desde 1e11 se toman como milisegundos.",
     "campos": [_tx("timestamp", "Unix timestamp", "1730000000", ahora=True, ancho="16rem"),
                {"name": "unidad", "label": "Unidad", "tipo": "select", "ancho": "12rem",
                 "opciones": [("auto", "Automática"), ("s", "Segundos"), ("ms", "Milisegundos")]},
                _tx("fecha", "Fecha (ISO 8601 o dd-mm-aaaa hh:mm:ss)", "2026-11-06 14:30:00", ancho="22rem"),
                _tx("zona", "Zona de la fecha", valor=h.ZONA_LOCAL, lista="zonas", ancho="16rem")],
     "acciones": [("a_fecha", "Timestamp → fecha", "bi-calendar-event"), ("a_timestamp", "Fecha → timestamp", "bi-123")]},
    {"slug": "fechas", "titulo": "Fechas", "icono": "bi-globe-americas", "manejador": _fechas,
     "descripcion": "Convierta una fecha y hora entre zonas horarias. Sin desplazamiento explícito se usa la zona de origen.",
     "campos": [_tx("fecha", "Fecha y hora", "2026-11-06 14:30:00", ancho="22rem"),
                _tx("origen", "Zona de origen", valor=h.ZONA_LOCAL, lista="zonas", ancho="16rem"),
                _tx("destino", "Zona de destino", valor="UTC", lista="zonas", ancho="16rem")],
     "acciones": [("convertir", "Convertir", "bi-arrow-left-right")]},
    {"slug": "mensaje", "titulo": "Armar mensaje (IA)", "icono": "bi-stars", "manejador": None,
     "descripcion": "Un agente de IA llena el esquema con sus datos y devuelve el mensaje en XML o JSON. "
                    "Cualquier forma de entrada sirve: se interpreta.",
     "aviso": "Los fragmentos se envían a la API de Claude (Anthropic). Use datos ficticios o anonimizados, no datos reales de clientes ni de cuentas.",
     "campos": [_ta("esquema", "Esquema (fragmento XSD/NXSD)", 10, '<xsd:element name="Monto" type="xsd:decimal"/>'),
                _ta("datos", "Datos (fragmento XML)", 8, "<Monto>1500.00</Monto>"),
                {"name": "formato", "label": "Formato de salida", "tipo": "select", "ancho": "12rem",
                 "opciones": [("xml", "XML"), ("json", "JSON")]},
                _ta("instrucciones", "Instrucciones (opcional)", 3, "Namespace, campos sin dato, etc.")],
     "acciones": [("armar", "Armar mensaje", "bi-stars")]},
]
POR_SLUG = {t["slug"]: t for t in HERRAMIENTAS}


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, name, ctx)


def _resultado(request: Request, **ctx) -> HTMLResponse:
    # 200 a propósito: htmx no reemplaza el contenido con respuestas 4xx.
    return render(request, "utilidades/_resultado.html", **ctx)


@router.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse("/utilidades/json", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_status(request: Request, job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return _resultado(request, error="La tarea ya no existe. Vuelva a armar el mensaje.")
    log = job.snapshot()
    if job.status == "running":
        return render(request, "utilidades/_job.html", job=job, log=log)
    if job.status == "error":
        return _resultado(request, error=job.error, log=log)
    return render(request, "utilidades/_mensaje.html", r=job.result, log=log)


@router.post("/mensaje", response_class=HTMLResponse)
async def armar(request: Request):
    form = await request.form()
    campos = [str(form.get(k, "")) for k in ("esquema", "datos", "formato", "instrucciones")]
    try:
        esquema, datos, formato, instrucciones = agente.validar_entrada(*campos)
    except agente.MensajeError as e:
        return _resultado(request, error=str(e))
    job = jobs.start("mensaje", lambda j: agente.armar_mensaje(
        esquema, datos, formato, instrucciones, progress=j.emit))
    return render(request, "utilidades/_job.html", job=job, log=job.snapshot())


@router.get("/{slug}", response_class=HTMLResponse)
def pagina(request: Request, slug: str):
    tool = POR_SLUG.get(slug)
    if tool is None:
        raise HTTPException(status_code=404)
    return render(request, "utilidades/herramienta.html", tool=tool, tabs=HERRAMIENTAS, zonas=h.ZONAS_SUGERIDAS)


@router.post("/{slug}", response_class=HTMLResponse)
async def ejecutar(request: Request, slug: str):
    tool = POR_SLUG.get(slug)
    if tool is None or tool["manejador"] is None:
        raise HTTPException(status_code=404)
    form = await request.form()
    datos = {k: str(v) for k, v in form.items()}
    try:
        ctx = tool["manejador"](datos)
    except ValueError as e:  # entrada del usuario inválida: se muestra, no es un 500
        return _resultado(request, error=str(e))
    return _resultado(request, **ctx)
