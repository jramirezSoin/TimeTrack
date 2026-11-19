"""Uso: python -m timetrack.pr_cli COMANDO [opciones]

Pull Requests en Azure DevOps (repo configurado en azure/config.json -> "repos"):
  estado --branch X [--destino main] [--repo R]
      Commits de X que faltan en el destino (irían en el PR) y commits del destino que le faltan a X.
  crear --branch X --titulo T [--descripcion D] [--destino main] [--repo R] [--draft] [--apply]
      Sin --apply solo previsualiza; con --apply crea el PR (si ya hay uno activo, lo reutiliza).

El PAT (AZURE_DEV_KEY) necesita el scope Code (Read & Write).
"""
from __future__ import annotations

import argparse
import sys


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pr", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for nombre in ("estado", "crear"):
        s = sub.add_parser(nombre)
        s.add_argument("--branch", required=True, help="branch de origen")
        s.add_argument("--destino", help="branch destino (por defecto repos.target_branch o main)")
        s.add_argument("--repo", help="repo (por defecto repos.default)")
        if nombre == "crear":
            s.add_argument("--titulo", required=True)
            s.add_argument("--descripcion", default="")
            s.add_argument("--draft", action="store_true")
            s.add_argument("--apply", action="store_true", help="crea el PR de verdad")
    return p


def _print_commits(titulo: str, commits: list[dict], total: int) -> None:
    print(f"{titulo} ({total})")
    for c in commits:
        print(f"  {c['short']} {c['autor']}: {c['mensaje']}")
    if total > len(commits):
        print(f"  ... y {total - len(commits)} más")


def main(argv=None, azure=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if azure is None:
            from .gateways import AzureReposGateway
            azure = AzureReposGateway()
        st = azure.status(args.branch, args.destino, args.repo)
        print(f"{st['source']} -> {st['target']}")
        if st.get("aviso"):
            print(f"AVISO: {st['aviso']}", file=sys.stderr)
        _print_commits("Pendientes de integrar (irían en el PR)", st["ahead"], st["ahead_count"])
        _print_commits("Le faltan a tu branch (están en destino)", st["behind"], st["behind_count"])

        if args.cmd == "crear":
            if not st["ahead_count"] and not st.get("aviso"):
                print("No hay commits nuevos que integrar; no se crea el PR.", file=sys.stderr)
                return 2
            existente = azure.active_pr(args.branch, args.destino, args.repo)
            if existente:
                print(f"Ya existe un PR activo: #{existente['pullRequestId']}")
            if not args.apply:
                print(f"\n[dry-run] PR '{args.titulo}'{' (draft)' if args.draft else ''}. "
                      "Usa --apply para crearlo.")
                return 0
            pr = azure.create_pr(args.branch, args.titulo, args.destino, args.descripcion,
                                 args.repo, args.draft)
            print(("Creado" if pr["creado"] else "Reutilizado") + f" PR #{pr['id']}: {pr['url']}")
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
