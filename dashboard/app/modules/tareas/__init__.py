from pathlib import Path

from ...registry import Module
from . import router as _router

module = Module(
    name="tareas",
    title="Tareas",
    description="Sus tareas como post-its: arrástrelas entre estados o al basurero para cerrarlas.",
    router=_router.router,
    icon="bi-sticky",
    templates_dir=Path(__file__).parent / "templates",
    summary=lambda: _router.service.summary(),
)
