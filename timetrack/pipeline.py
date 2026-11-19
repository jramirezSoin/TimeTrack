"""Orquestación: validar -> preview -> (confirmar) -> enviar a Azure y SIGES -> ledger.

Tres piezas reutilizables por el CLI y por el dashboard web:
- build_preview(): calcula qué se enviaría (sin escrituras).
- format_preview(): lo muestra como texto.
- execute(): envía lo previsualizado y lo registra en el ledger.
run() las encadena para el CLI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .adapters.azure import build_azure_tasks
from .adapters.siges import build_siges_days
from .catalog import Catalog
from .ledger import Ledger, pending_activities, pending_days
from .models import Plan
from .resolver import resolve_incident
from .validate import validate_plan


@dataclass
class IncidentStatus:
    state: str  # "catalogo" | "azure" | "nuevo"
    azure_id: int | None
    label: str


@dataclass
class Preview:
    az_tasks: list[dict]
    sg_days: list[dict]
    incidents: dict[str, IncidentStatus] = field(default_factory=dict)

    @property
    def pending(self) -> bool:
        return bool(self.az_tasks or self.sg_days)

    @property
    def new_incidents(self) -> list[str]:
        """Incidentes que no existen en Azure: requieren un título para crear el Bug."""
        return [i for i, s in self.incidents.items() if s.state == "nuevo"]


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    azure: list[dict] = field(default_factory=list)  # {title, incident, ref}
    siges: list[dict] = field(default_factory=list)  # {fecha, status}

    @property
    def ok(self) -> bool:
        return not self.errors


def _incident_status(incidente, catalog, azure) -> IncidentStatus:
    """Estado del incidente sin efectos secundarios (para el preview)."""
    hit = catalog.get_incident(incidente)
    if hit:
        return IncidentStatus("catalogo", hit["azure_id"], f"id {hit['azure_id']} (catálogo)")
    found = azure.find_incident(incidente)
    if found:
        return IncidentStatus("azure", found, f"id {found} (Azure)")
    return IncidentStatus("nuevo", None, "NO EXISTE: se pedirá título y se creará el Bug")


def build_preview(plan: Plan, *, catalog: Catalog, ledger: Ledger, azure) -> Preview:
    """Valida el plan y calcula lo pendiente. Lanza PlanError si algún día no suma 8h.

    No escribe nada en Azure, SIGES, catálogo ni ledger.
    """
    validate_plan(plan)

    cache: dict = {}

    def iteration_for(fecha):
        if fecha not in cache:
            cache[fecha] = azure.iteration_for(fecha)
        return cache[fecha]

    az_plan = pending_activities(plan, "azure", ledger)
    sg_plan = pending_days(plan, "siges", ledger)
    az_tasks = build_azure_tasks(az_plan, iteration_for) if az_plan else []
    sg_days = build_siges_days(sg_plan, iteration_for) if sg_plan else []

    incidents: dict[str, IncidentStatus] = {}
    for t in az_tasks:
        inc = t.get("incident")
        if inc and inc not in incidents:
            incidents[inc] = _incident_status(inc, catalog, azure)

    return Preview(az_tasks, sg_days, incidents)


def format_preview(preview: Preview) -> list[str]:
    """Líneas de texto del preview (las que imprime el CLI)."""
    lines = ["=== AZURE DEVOPS ==="]
    if not preview.az_tasks:
        lines.append("  (nada pendiente)")
    for t in preview.az_tasks:
        if "incident" in t:
            estado = preview.incidents[t["incident"]].label
            lines.append(f"  Task '{t['title']}' bajo incidente {t['incident']} [{estado}] | {t['hours']} h | {t['iteration']}")
        else:
            lines.append(f"  Task agrupada '{t['title']}' bajo '{t['parent_title']}' | {t['hours']} h | {t['iteration']}")
        lines.append("    (si ya existe: se suman horas y se concatena la descripción)")
        for linea in t["description"].split("<br>"):
            lines.append(f"    - {linea}")

    lines.append("=== SIGES ===")
    if not preview.sg_days:
        lines.append("  (nada pendiente)")
    for d in preview.sg_days:
        lines.append(f"  {d['fecha']}  ({sum(x['horas'] for x in d['tareas'])} h)")
        for x in d["tareas"]:
            lines.append(f"    {x['numIdent']} | {x['horas']} h | {x['comentario']}")
    return lines

def clean_tasks(tareas, incidents):
    cleaned = []
    for t in tareas:
        incident = t.pop("incident", None)
        comentario = t["comentario"]
        if incident and incident in incidents:
            comentario = str(incidents[incident].azure_id) + " - " + comentario
        cleaned.append({**t, "comentario": comentario})
    return cleaned

def execute(
    preview: Preview,
    *,
    catalog: Catalog,
    ledger: Ledger,
    azure,
    siges,
    ask_title: Callable[[str], str],
    cerrar_dia: bool = False,
    out: Callable[[str], None] = print,
) -> Result:
    """Envía lo previsualizado. Si algo falla sigue con el resto y lo reporta en Result.errors."""
    result = Result()

    for t in preview.az_tasks:
        try:
            if "incident" in t:
                pid = resolve_incident(t["incident"], catalog, azure, ask_title, t["iteration"])
                ref = azure.upsert_child(pid, t)
            else:
                ref = azure.upsert_grouped(t)
            if isinstance(ref, tuple):  # (id, 'creada' | 'actualizada')
                ref = ref[0]
            fechas = t.get("ref_fechas", [])
            for i, k in enumerate(t["ref_keys"]):
                meta = {"fecha": fechas[i]} if i < len(fechas) else {}
                ledger.add(k, sistema="azure", ref=str(ref), **meta)
            result.azure.append({"title": t["title"], "incident": t.get("incident"), "ref": ref})
        except Exception as e:  # sigue con el resto y reporta al final
            msg = f"Azure '{t['title']}': {e}"
            result.errors.append(msg)
            out(f"❌ {msg}")

    for d in preview.sg_days:
        try:
            status, body = siges.send_day(d["fecha"], clean_tasks(d["tareas"], preview.incidents), cerrar_dia)
            out(f"SIGES {d['fecha']}: HTTP {status} {body[:200]}")
            ledger.add(d["ref_key"], sistema="siges", fecha=d["fecha"])
            result.siges.append({"fecha": d["fecha"], "status": status})
        except Exception as e:
            msg = f"SIGES {d['fecha']}: {e}"
            result.errors.append(msg)
            out(f"❌ {msg}")
    return result


def run(
    plan: Plan,
    *,
    catalog: Catalog,
    ledger: Ledger,
    azure,
    siges,
    apply: bool = False,
    cerrar_dia: bool = False,
    ask_title: Callable[[str], str] = input,
    confirm: Callable[[str], bool] = lambda msg: input(msg).strip().lower() in ("s", "si", "sí", "y"),
    out: Callable[[str], None] = print,
) -> int:
    """Devuelve 0 si todo salió bien (o fue dry-run), 1 si hubo errores o se canceló."""
    preview = build_preview(plan, catalog=catalog, ledger=ledger, azure=azure)
    for line in format_preview(preview):
        out(line)

    if not apply:
        out("\nDry-run: no se envió nada. Use --apply para enviar.")
        return 0
    if not preview.pending:
        out("\nNada pendiente.")
        return 0
    if not confirm("\n¿Enviar a Azure y SIGES? (s/N): "):
        out("Cancelado.")
        return 1

    result = execute(
        preview, catalog=catalog, ledger=ledger, azure=azure, siges=siges,
        ask_title=ask_title, cerrar_dia=cerrar_dia, out=out,
    )
    out(f"\nTerminado con {len(result.errors)} error(es).")
    return 0 if result.ok else 1
