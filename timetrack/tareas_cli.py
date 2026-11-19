"""Uso: python -m timetrack.tareas_cli COMANDO [opciones]

Tareas personales de la semana (locales, en data/tareas.json):
  nueva "título" [--incidente N] [--semana 2026-W45] [--notas TXT]
  mover ID {pendiente,en_proceso,entregada,cerrada}
  listar [--semana 2026-W45 | --todas] [--estado ESTADO]
  resumen [--semana 2026-W45 | --todas]
  editar ID [--titulo T] [--semana S] [--notas N]
  eliminar ID

Con --incidente, si no está en el catálogo ni en Azure, se crea su Bug padre (con el título de la tarea).
"""
from __future__ import annotations

import argparse
import sys

from .tareas import Estado, Tarea, TareaError, TaskStore, semana_de

_ESTADOS = [e.value for e in Estado]
_ETIQUETA = {
    Estado.PENDIENTE: "Pendientes",
    Estado.EN_PROCESO: "En proceso",
    Estado.ENTREGADA: "Entregadas",
    Estado.CERRADA: "Cerradas",
}


def _linea(t: Tarea) -> str:
    inc = f" [{t.incidente}]" if t.incidente else ""
    az = f" (Azure {t.azure_id})" if t.azure_id else ""
    return f"  #{t.id}{inc} {t.titulo}{az}"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tareas", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("nueva", help="crea una tarea")
    n.add_argument("titulo")
    n.add_argument("--incidente")
    n.add_argument("--semana", help="AAAA-Wnn (por defecto, la actual)")
    n.add_argument("--notas", default="")

    m = sub.add_parser("mover", help="cambia el estado")
    m.add_argument("id", type=int)
    m.add_argument("estado", choices=_ESTADOS)

    for nombre in ("listar", "resumen"):
        l = sub.add_parser(nombre)
        g = l.add_mutually_exclusive_group()
        g.add_argument("--semana", help="AAAA-Wnn (por defecto, la actual)")
        g.add_argument("--todas", action="store_true", help="todas las semanas")
        if nombre == "listar":
            l.add_argument("--estado", choices=_ESTADOS)

    e = sub.add_parser("editar")
    e.add_argument("id", type=int)
    e.add_argument("--titulo")
    e.add_argument("--semana")
    e.add_argument("--notas")

    d = sub.add_parser("eliminar")
    d.add_argument("id", type=int)
    return p


def main(argv=None, store: TaskStore | None = None, azure=None, ask_title=None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = store or TaskStore()
        semana = None if getattr(args, "todas", False) else (getattr(args, "semana", None) or semana_de())

        if args.cmd == "nueva":
            kw = {}
            if args.incidente:
                from .catalog import Catalog
                from .gateways import AzureGateway
                azure = azure or AzureGateway()
                kw = dict(catalog=Catalog(), gateway=azure, ask_title=ask_title)
            t = store.crear(args.titulo, incidente=args.incidente, semana=args.semana,
                            notas=args.notas, **kw)
            print(f"Creada #{t.id} en {t.semana}." + (f" Padre Azure: {t.azure_id}" if t.azure_id else ""))
        elif args.cmd == "mover":
            t = store.mover(args.id, Estado(args.estado))
            print(f"#{t.id} -> {t.estado.value}")
        elif args.cmd == "listar":
            tareas = store.listar(semana=semana, estado=Estado(args.estado) if args.estado else None)
            print(f"Semana: {semana or 'todas'}")
            for est in Estado:
                grupo = [t for t in tareas if t.estado == est]
                if grupo:
                    print(f"{_ETIQUETA[est]} ({len(grupo)})")
                    print("\n".join(_linea(t) for t in grupo))
            if not tareas:
                print("Sin tareas.")
        elif args.cmd == "resumen":
            print(f"Semana: {semana or 'todas'}")
            for est, n in store.resumen(semana).items():
                print(f"  {_ETIQUETA[est]:<11} {n}")
        elif args.cmd == "editar":
            if args.titulo is None and args.semana is None and args.notas is None:
                print("Indique al menos --titulo, --semana o --notas.", file=sys.stderr)
                return 2
            t = store.editar(args.id, titulo=args.titulo, semana=args.semana, notas=args.notas)
            print(f"Editada #{t.id}.")
        elif args.cmd == "eliminar":
            store.eliminar(args.id)
            print(f"Eliminada #{args.id}.")
    except (TareaError, ValueError) as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
