from pathlib import Path

from ...registry import Module
from . import router as _router

module = Module(
    name="pullrequests",
    title="Pull Requests",
    description="Vea los commits que faltan entre su branch y la principal en Azure DevOps y cree el Pull Request.",
    router=_router.router,
    icon="bi-git",
    templates_dir=Path(__file__).parent / "templates",
    summary=lambda: ["Compare una branch con la principal y cree el PR."],
)
