"""Uso: python -m timetrack ENTRADA [--apply] [--cerrar-dia] [--yes] [--guardar-plan RUTA]

ENTRADA puede ser:
  - un .txt con la prosa (la interpreta el agente de Claude), o
  - un .json con un plan ya armado (ver tests/plan_ejemplo.json).
Por defecto es dry-run: solo muestra qué se enviaría.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import ExtraccionError, parse_prose
from .catalog import Catalog
from .gateways import AzureGateway, SigesGateway
from .ledger import Ledger
from .models import Plan
from .pipeline import run
from .validate import PlanError


def load_plan(path: Path) -> Plan:
    texto = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return Plan.model_validate(json.loads(texto))
    return parse_prose(texto, verbose=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="timetrack", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("entrada", help="reporte .txt (prosa) o plan .json")
    p.add_argument("--apply", action="store_true", help="enviar de verdad (por defecto: dry-run)")
    p.add_argument("--cerrar-dia", action="store_true", help="cerrar el día en SIGES")
    p.add_argument("--yes", action="store_true", help="no pedir confirmación")
    p.add_argument("--guardar-plan", metavar="RUTA",
                   help="guarda el plan interpretado en un .json para revisarlo o reutilizarlo")
    args = p.parse_args(argv)

    try:
        plan = load_plan(Path(args.entrada))
    except ExtraccionError as e:
        print(e, file=sys.stderr)
        return 2

    if args.guardar_plan:
        Path(args.guardar_plan).write_text(
            plan.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        print(f"Plan guardado en {args.guardar_plan}")

    confirm = (lambda _m: True) if args.yes else (
        lambda m: input(m).strip().lower() in ("s", "si", "sí", "y")
    )
    try:
        return run(
            plan,
            catalog=Catalog(),
            ledger=Ledger(),
            azure=AzureGateway(),
            siges=SigesGateway(),
            apply=args.apply,
            cerrar_dia=args.cerrar_dia,
            ask_title=lambda inc: input(f"Título para el Bug del incidente {inc}: "),
            confirm=confirm,
        )
    except PlanError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
