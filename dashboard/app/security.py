"""Protecciones para un servidor local que puede escribir en sistemas reales.

- Solo se atiende a Host de localhost (evita DNS rebinding).
- Toda petición que cambia estado (POST, etc.) debe traer:
    * un Origin igual al Host (si el navegador lo envía), y
    * el token CSRF de la sesión del servidor en la cabecera X-CSRF-Token.
  Una página ajena no puede leer ese token, así que no puede disparar envíos.
"""
from __future__ import annotations

import os
import secrets
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
DEFAULT_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6: [::1]:8000
        return host.split("]")[0] + "]"
    return host.split(":")[0]


def install(app: FastAPI, token: str, allowed_hosts: tuple[str, ...] | None = None) -> None:
    if allowed_hosts is None:
        extra = os.environ.get("DASHBOARD_ALLOWED_HOSTS", "")
        allowed_hosts = DEFAULT_HOSTS + tuple(h.strip().lower() for h in extra.split(",") if h.strip())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host_header = request.headers.get("host", "")
        if _hostname(host_header) not in allowed_hosts:
            return PlainTextResponse("Host no permitido.", status_code=400)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc.lower() != host_header.strip().lower():
                return PlainTextResponse("Origen no permitido.", status_code=403)
            sent = request.headers.get("x-csrf-token", "")
            if not secrets.compare_digest(sent, token):
                return PlainTextResponse("Token CSRF inválido o ausente.", status_code=403)
        return await call_next(request)
