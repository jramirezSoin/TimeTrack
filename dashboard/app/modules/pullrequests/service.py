"""Lógica del módulo de Pull Requests: envuelve `AzureReposGateway` (no depende de FastAPI)."""
from __future__ import annotations


def _real_repos():
    from timetrack.gateways import AzureReposGateway
    return AzureReposGateway()


class PullRequestsService:
    def __init__(self, *, repos_factory=None):
        self._factory = repos_factory or _real_repos
        self._repos = None

    @property
    def repos(self):
        if self._repos is None:
            self._repos = self._factory()
        return self._repos

    def branches(self) -> list[str]:
        return self.repos.branches()

    def destino_por_defecto(self) -> str:
        return self.repos.default_target()

    def origen_por_defecto(self) -> str:
        return self.repos.default_source()

    def mis_prs(self) -> list[dict]:
        return self.repos.my_active_prs()

    def estado(self, branch: str, destino: str | None = None) -> dict:
        """Commits por integrar / faltantes y PR activo (si existe) entre `branch` y `destino`."""
        branch = branch.strip()
        if not branch:
            raise ValueError("Indique la branch de origen.")
        destino = (destino or "").strip() or None
        st = self.repos.status(branch, destino)
        st["pr_activo"] = self.repos.active_pr(branch, st["target"])
        return st

    def crear(self, branch: str, titulo: str, destino: str | None = None,
              descripcion: str = "", draft: bool = False) -> dict:
        if not branch.strip() or not titulo.strip():
            raise ValueError("Indique la branch y el título del PR.")
        destino = (destino or "").strip() or None
        return self.repos.create_pr(branch.strip(), titulo.strip(), destino, descripcion, None, draft)
