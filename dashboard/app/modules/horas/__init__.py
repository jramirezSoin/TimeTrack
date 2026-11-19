from pathlib import Path

from ...registry import Module
from . import router as _router

module = Module(
    name="horas",
    title="Reporte de horas",
    description="Pegue su reporte en prosa y envíelo a Azure DevOps y SIGES.",
    router=_router.router,
    icon="bi-clock-history",
    templates_dir=Path(__file__).parent / "templates",
    summary=lambda: _router.service.summary(),
)
