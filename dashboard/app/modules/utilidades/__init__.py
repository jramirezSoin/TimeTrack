from pathlib import Path

from ...registry import Module
from . import router as _router

module = Module(
    name="utilidades",
    title="Utilidades",
    description="JSON, XML, Base64, JWT, fechas y timestamps, y un agente que arma mensajes desde un esquema.",
    router=_router.router,
    icon="bi-tools",
    templates_dir=Path(__file__).parent / "templates",
)
