"""Módulos enchufables: cada proyecto es un paquete en app/modules/<nombre>/ que expone `module`."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import APIRouter


@dataclass
class Module:
    name: str                       # segmento de URL: /<name>/
    title: str                      # texto del menú y de la tarjeta
    description: str
    router: APIRouter
    icon: str = "bi-app"            # clase de Bootstrap Icons (menú y tarjeta de la portada)
    templates_dir: Path | None = None
    summary: Callable[[], list[str]] | None = None  # líneas para la tarjeta de la portada


def discover(package: str) -> list[Module]:
    """Importa cada subpaquete de `package` y recoge su atributo `module`."""
    pkg = importlib.import_module(package)
    found: list[Module] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if not info.ispkg:
            continue
        mod = importlib.import_module(f"{package}.{info.name}")
        m = getattr(mod, "module", None)
        if isinstance(m, Module):
            found.append(m)
    return found
