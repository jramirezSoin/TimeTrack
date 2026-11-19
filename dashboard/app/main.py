"""Dashboard centralizado. Arranque (desde la raíz del proyecto):

    uvicorn dashboard.app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import security
from .registry import Module, discover

APP_DIR = Path(__file__).resolve().parent
PWA_DIR = APP_DIR / "static" / "pwa"
NO_CACHE = {"Cache-Control": "no-cache"}  # el navegador revalida siempre: así se detectan las actualizaciones


def create_app(
    *, modules: list[Module] | None = None, allowed_hosts: tuple[str, ...] | None = None
) -> FastAPI:
    app = FastAPI(title="Dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    mods = modules if modules is not None else discover(f"{__package__}.modules")
    dirs = [APP_DIR / "templates"] + [m.templates_dir for m in mods if m.templates_dir]
    templates = Jinja2Templates(directory=dirs)

    token = secrets.token_urlsafe(32)
    templates.env.globals.update(csrf_token=token, modules=mods)
    app.state.templates = templates
    app.state.csrf_token = token

    for m in mods:
        app.include_router(m.router, prefix=f"/{m.name}")
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    security.install(app, token, allowed_hosts)

    # PWA: el manifiesto y el service worker se sirven desde la raíz (el alcance del SW depende de su ruta).
    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(PWA_DIR / "manifest.webmanifest", media_type="application/manifest+json", headers=NO_CACHE)

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(PWA_DIR / "sw.js", media_type="text/javascript", headers=NO_CACHE)

    @app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
    def offline():
        return FileResponse(PWA_DIR / "offline.html", media_type="text/html", headers=NO_CACHE)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        cards = []
        for m in mods:
            try:
                lines = m.summary() if m.summary else []
            except Exception as e:  # una tarjeta rota no debe tumbar la portada
                lines = [f"No se pudo leer el resumen: {e}"]
            cards.append({"module": m, "lines": lines})
        return templates.TemplateResponse(request, "home.html", {"cards": cards})

    return app


app = create_app()
