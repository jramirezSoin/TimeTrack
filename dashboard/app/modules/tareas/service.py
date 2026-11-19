"""Lógica del módulo de tareas: envuelve `timetrack.tareas.TaskStore` (no depende de FastAPI)."""
from __future__ import annotations

import threading

from timetrack.catalog import Catalog
from timetrack.tareas import Estado, Tarea, TareaError, TaskStore

# Estados visibles en el tablero, en orden de columnas. Las cerradas no se muestran.
ABIERTOS = (Estado.PENDIENTE, Estado.EN_PROCESO, Estado.ENTREGADA)


def _real_azure():
    from timetrack.gateways import AzureGateway
    return AzureGateway()


class TareasService:
    def __init__(self, *, store_path=None, catalog_path=None, azure_factory=None):
        self.store_path = store_path
        self.catalog_path = catalog_path
        self._azure_factory = azure_factory or _real_azure
        self._azure = None
        self._lock = threading.Lock()

    def store(self) -> TaskStore:
        return TaskStore(self.store_path) if self.store_path else TaskStore()

    def catalog(self) -> Catalog:
        return Catalog(self.catalog_path) if self.catalog_path else Catalog()

    @property
    def azure(self):
        if self._azure is None:
            self._azure = self._azure_factory()
        return self._azure

    # --- lectura ---
    def tablero(self) -> dict[Estado, list[Tarea]]:
        """Tareas abiertas por estado; la modificada más recientemente va primero."""
        with self._lock:
            todas = self.store().listar()
        return {
            e: sorted((t for t in todas if t.estado == e), key=lambda t: (t.actualizada, t.id), reverse=True)
            for e in ABIERTOS
        }

    def summary(self) -> list[str]:
        t = self.tablero()
        return [f"{len(t[Estado.PENDIENTE])} pendiente(s) · {len(t[Estado.EN_PROCESO])} en proceso · "
                f"{len(t[Estado.ENTREGADA])} entregada(s)"]

    # --- escritura ---
    def nueva(self, titulo: str, incidente: str | None = None) -> Tarea:
        """Crea la tarea. Con incidente nuevo, el Bug padre de Azure se crea con el título de la tarea."""
        incidente = (incidente or "").strip() or None
        with self._lock:
            kw = {}
            if incidente:
                kw = dict(catalog=self.catalog(), gateway=self.azure)
            return self.store().crear(titulo, incidente=incidente, **kw)

    def mover(self, id: int, estado: str) -> Tarea:
        try:
            nuevo = Estado(estado)
        except ValueError:
            raise TareaError(f"Estado inválido: {estado!r}.") from None
        with self._lock:
            return self.store().mover(id, nuevo)
