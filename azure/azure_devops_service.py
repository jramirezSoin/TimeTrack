import base64
import json
import os
import argparse
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import requests

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "config.json", encoding="utf-8") as f:
    config = json.load(f)

ORG = config["org"]
PROJECT = config["project"]
TEAM = config["team"]
WORK_ITEM_TYPE = "Bug"
AZURE_ENDPOINT = f"https://dev.azure.com/{ORG}/{PROJECT}"
AREA= config["area"]

SUMMARY_FIELDS = [
    ("System.WorkItemType", "Tipo"),
    ("System.Title", "Título"),
    ("System.State", "Estado"),
    ("System.AssignedTo", "Asignado a"),
    ("System.AreaPath", "Area"),
    ("System.IterationPath", "Iteración"),
    ("System.CreatedDate", "Creado"),
    ("Microsoft.VSTS.Common.Activity", "Actividad"),
    ("Microsoft.VSTS.Scheduling.OriginalEstimate", "Estimado"),
    ("Microsoft.VSTS.Scheduling.RemainingWork", "Restante"),
    ("Microsoft.VSTS.Scheduling.CompletedWork", "Completado"),
    ("Custom.Sistema", "Sistema"),
]


_auth_cache = None
_iteration_cache = None


def _auth():
    """PAT en base64; se lee de AZURE_DEV_KEY la primera vez que se necesita."""
    global _auth_cache
    if _auth_cache is None:
        token = os.environ.get("AZURE_DEV_KEY")
        if not token:
            raise RuntimeError(
                "Falta la variable de entorno AZURE_DEV_KEY (PAT de Azure DevOps). "
                "Si la acabas de crear, abre una terminal nueva."
            )
        _auth_cache = base64.b64encode(f":{token}".encode()).decode()
    return _auth_cache


def get_iteration():
    """Iteración actual del equipo (consulta perezosa, en caché)."""
    global _iteration_cache
    if _iteration_cache is None:
        _iteration_cache = get_current_iteration()
    return _iteration_cache


def ado_fetch(url, method="GET", body=None, headers=None):
    all_headers = {
        "Authorization": f"Basic {_auth()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        **(headers or {}),
    }
    res = requests.request(
        method,
        url,
        data=json.dumps(body) if body is not None else None,
        headers=all_headers,
        timeout=60,
    )
    if not res.ok:
        raise RuntimeError(f"{res.status_code} {res.reason}: {res.text}")
    return res.json()

def ado_patch_fetch(url, body, method="POST"):
    res = requests.request(
        method,
        url,
        data=json.dumps(body),
        headers={
            "Authorization": f"Basic {_auth()}",
            "Content-Type": "application/json-patch+json",
            "Accept": "application/json",
        },
        timeout=60,
    )
    if not res.ok:
        raise RuntimeError(f"{res.status_code} {res.reason}\n\n{res.text}")
    return res.json()

def _run_wiql(query, quiet=False):
    url = f"{AZURE_ENDPOINT}/_apis/wit/wiql?api-version=7.1"
    result = ado_fetch(url, method="POST", body={"query": query})
    ids = [w["id"] for w in result["workItems"]]
    if not ids:
        if not quiet:
            print("No se encontraron work items para ese sprint.")
        return None
    return ids

def inspect_work_item(work_item_id):
    url = (
        f"{AZURE_ENDPOINT}/_apis/wit/workitems/"
        f"{work_item_id}?$expand=all&api-version=7.1"
    )
    result = ado_fetch(url)
    for key, value in result["fields"].items():
        if "sistema" in key.lower() or "soa" in str(value).lower():
            print(f"{key} = {value}")

def get_sprint_ids(iteration=None):
    """Ids de mis work items en `iteration` (path); sin argumento, el sprint actual."""
    iteration = str(iteration or get_iteration()).replace("'", "''")
    query = f"""
    SELECT [System.Id]
    FROM WorkItems
    WHERE
      [System.TeamProject] = '{PROJECT}'
      AND [System.IterationPath] = '{iteration}'
      AND [System.AreaPath] = '{AREA}'
      AND (
        [System.AssignedTo] = 'Joseph Ramirez Barquero'
      )
    ORDER BY [System.WorkItemType], [System.Id]
    """
    return _run_wiql(query)

def find_work_item(name, quiet=False):
    safe_name = str(name).replace("'", "''")
    query = f"""
    SELECT [System.Id]
    FROM WorkItems
    WHERE
      [System.TeamProject] = '{PROJECT}'
      AND [System.AreaPath] = '{AREA}'
      AND [System.Title] contains '{safe_name}'
      AND [System.WorkItemType] <> 'Task'
      AND [System.WorkItemType] <> 'Test Suite'
    ORDER BY [System.CreatedDate] DESC
    """
    return _run_wiql(query, quiet=quiet)

def _fetch_batch(ids):
    url = f"{AZURE_ENDPOINT}/_apis/wit/workitemsbatch?api-version=7.1"
    result = ado_fetch(url, method="POST", body={"ids": ids, "$expand": "Relations"})
    return result["value"]

def _parent_id(item):
    for rel in item.get("relations") or []:
        if rel.get("rel") == "System.LinkTypes.Hierarchy-Reverse":
            return int(rel["url"].split("/")[-1])
    return None

def get_sprint_items(ids):
    items = []
    for item in _fetch_batch(ids):
        f = item["fields"]
        items.append({
            "id": item["id"],
            "type": f.get("System.WorkItemType"),
            "title": f.get("System.Title"),
            "description": f.get("System.Description"),
            "date": f.get("System.CreatedDate"),
            "state": f.get("System.State"),
            "assignedTo": (f.get("System.AssignedTo") or {}).get("displayName", ""),
            "estimated": f.get("Microsoft.VSTS.Scheduling.OriginalEstimate"),
            "remaining": f.get("Microsoft.VSTS.Scheduling.RemainingWork"),
            "completed": f.get("Microsoft.VSTS.Scheduling.CompletedWork"),
            "parentId": _parent_id(item),
        })
    return items

def get_sprint_items_p(ids):
    items = []
    for item in _fetch_batch(ids):
        f = item["fields"]
        items.append({
            "id": item["id"],
            "type": f.get("System.WorkItemType"),
            "title": (f.get("System.Title") or "")[:100],
            "date": f.get("System.CreatedDate"),
            "state": f.get("System.State"),
            "assignedTo": (f.get("System.AssignedTo") or {}).get("displayName", ""),
        })
    return items

def get_iterations():
    """Todas las iteraciones (sprints) del equipo: dicts con name, path y attributes."""
    url = f"{AZURE_ENDPOINT}/{TEAM}/_apis/work/teamsettings/iterations?api-version=7.1"
    return ado_fetch(url)["value"]

def get_my_sprint(iteration):
    """Mis work items del sprint `iteration` (path) y los de sus padres: {'items': [...], 'parents': [...]}."""
    ids = get_sprint_ids(iteration)
    if not ids:
        return {"items": [], "parents": []}
    items = get_sprint_items(ids)
    parent_ids = sorted({i["parentId"] for i in items if i["parentId"] is not None})
    parents = get_sprint_items(parent_ids) if parent_ids else []
    return {"items": items, "parents": parents}

def get_current_iteration():
    url = (
        f"{AZURE_ENDPOINT}/{TEAM}/_apis/work/teamsettings/"
        "iterations?$timeframe=current&api-version=7.1"
    )
    return ado_fetch(url)["value"][0]["path"]

def get_iteration_for(fecha):
    """Devuelve el path de la iteración (sprint) que contiene `fecha`.

    fecha: date, datetime o str 'YYYY-MM-DD' / 'DD-MM-YYYY'.
    Lanza ValueError si ninguna iteración del equipo cubre esa fecha.
    """
    if isinstance(fecha, datetime):
        dia = fecha.date()
    elif isinstance(fecha, date):
        dia = fecha
    else:
        texto = str(fecha).strip()[:10]
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                dia = datetime.strptime(texto, fmt).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Fecha inválida: {fecha!r} (use YYYY-MM-DD o DD-MM-YYYY)")

    url = f"{AZURE_ENDPOINT}/{TEAM}/_apis/work/teamsettings/iterations?api-version=7.1"
    for it in ado_fetch(url)["value"]:
        attrs = it.get("attributes") or {}
        inicio, fin = attrs.get("startDate"), attrs.get("finishDate")
        if not inicio or not fin:
            continue  # iteración sin fechas
        if (datetime.strptime(inicio[:10], "%Y-%m-%d").date()
                <= dia
                <= datetime.strptime(fin[:10], "%Y-%m-%d").date()):
            return it["path"]
    raise ValueError(f"Ninguna iteración del equipo cubre la fecha {dia.isoformat()}")

def print_table(rows):
    """Reemplazo simple de console.table."""
    if isinstance(rows, dict):
        rows = [rows]
    if not rows:
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))

def print_allowed_values(missing):
    """Muestra los valores permitidos de los campos requeridos que faltan."""
    print("\nValores permitidos para los campos requeridos que faltan en parent_task.json:")
    for ref in missing:
        url = (
            f"{AZURE_ENDPOINT}/_apis/wit/workitemtypes/"
            f"{WORK_ITEM_TYPE}/fields/{ref}?$expand=allowedValues&api-version=7.1"
        )
        try:
            info = ado_fetch(url)
            print(f"  {ref}: {info.get('allowedValues')}")
        except Exception as error:
            print(f"  {ref}: (no se pudo consultar: {error})")

def print_sprint_items():
    ids = get_sprint_ids()
    if not ids:
        return
    items = get_sprint_items(ids)
    parent_ids = sorted({i["parentId"] for i in items if i["parentId"] is not None})
    items_p = get_sprint_items_p(parent_ids)
    print_table(items_p)
    print_table(items)

def add_field(body, field, value):
    if value is not None and value != "":
        body.append({"op": "add", "path": f"/fields/{field}", "value": value})

def get_workitem(work_item_id):
    url = (
        f"{AZURE_ENDPOINT}/_apis/wit/workitems/"
        f"{work_item_id}?$expand=all&api-version=7.1"
    )
    return ado_fetch(url)

def _fmt(value):
    if isinstance(value, dict):
        return value.get("displayName") or json.dumps(value, ensure_ascii=False)
    return value

def print_workitem():
    parser = argparse.ArgumentParser(description="Consulta un work item de Azure DevOps")
    parser.add_argument("id", type=int, help="ID del work item")
    parser.add_argument("--all", action="store_true", help="mostrar todos los campos")
    parser.add_argument("--json", action="store_true", help="imprimir el JSON completo")
    args = parser.parse_args()

    try:
        item = get_workitem(args.id)
    except Exception as error:
        print(f"❌ Error: {error}")
        return

    if args.json:
        print(json.dumps(item, indent=2, ensure_ascii=False))
        return

    fields = item["fields"]
    print(f"Work item {item['id']}\n")

    if args.all:
        for key, value in fields.items():
            print(f"{key}: {_fmt(value)}")
    else:
        for key, label in SUMMARY_FIELDS:
            if key in fields:
                print(f"{label}: {_fmt(fields[key])}")

    relations = [r for r in item.get("relations") or [] if "workItems" in r.get("url", "")]
    if relations:
        print("\nRelaciones:")
        for r in relations:
            related_id = r["url"].split("/")[-1]
            print(f"  {r['rel']} -> {related_id}")

    print(f"\nURL: {AZURE_ENDPOINT}/_workitems/edit/{item['id']}")
    

def create_child_task(task=None):
    """Crea una Task hija. Si no se pasa `task`, lee tasks.json (modo manual)."""
    if task is None:
        with open(BASE_DIR / "tasks.json", encoding="utf-8") as f:
            task = json.load(f)["task"]
    print(f"Creando: {task.get('title')} -> Incidente {task.get('incident')}")

    # Si el resolver ya conoce el id del incidente (catálogo), no se vuelve a buscar.
    if task.get("parent_id"):
        return _create_task(task["parent_id"], task)

    incident_ids = find_work_item(task.get("incident"))
    if not incident_ids:
        raise RuntimeError(f"No se encontró el incidente: {task.get('incident')}")
    incident_items = get_sprint_items(incident_ids)
    return _create_task(incident_items[0]["id"], task)

def _create_task(parent_id, task):
    """Crea una Task hija de `parent_id`. Usa task['iteration'] o, si falta, el sprint actual."""
    url = f"{AZURE_ENDPOINT}/_apis/wit/workitems/$Task?api-version=7.1"

    body = []
    add_field(body, "System.Title", task.get("title"))
    add_field(body, "System.AreaPath", AREA)
    add_field(body, "System.IterationPath", task.get("iteration") or get_iteration())
    add_field(body, "System.Description", f"<div>{task.get('description', '')}</div>")
    add_field(body, "Microsoft.VSTS.Common.Activity", config["activity"])
    add_field(body, "Microsoft.VSTS.Scheduling.OriginalEstimate", task.get("hours"))
    add_field(body, "Microsoft.VSTS.Scheduling.RemainingWork", "0")
    add_field(body, "Microsoft.VSTS.Scheduling.CompletedWork", task.get("hours"))
    add_field(body, "Custom.Sistema", config["sistema"])

    body.append({
        "op": "add",
        "path": "/relations/-",
        "value": {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": f"{AZURE_ENDPOINT}/_apis/wit/workItems/{parent_id}",
            "attributes": {"comment": "Creado automáticamente desde script"},
        },
    })

    created = ado_patch_fetch(url, body)
    print(f"✅ {created['id']} - {created['fields']['System.Title']}")
    return created["id"]

def _find_by_title(title, iteration, only_tasks):
    safe = str(title).replace("'", "''")
    tipo = "=" if only_tasks else "<>"
    query = f"""
    SELECT [System.Id]
    FROM WorkItems
    WHERE
      [System.TeamProject] = '{PROJECT}'
      AND [System.AreaPath] = '{AREA}'
      AND [System.IterationPath] = '{iteration}'
      AND [System.Title] = '{safe}'
      AND [System.WorkItemType] {tipo} 'Task'
    ORDER BY [System.CreatedDate] DESC
    """
    return _run_wiql(query, quiet=True)

def upsert_grouped_task(task):
    """Crea la Task agrupada (p. ej. 'DEV - Joseph Ramirez') bajo el padre del sprint.

    Si ya existe en ese sprint y padre, la edita: suma las horas y concatena la
    descripción. Devuelve (id, 'creada' | 'actualizada').
    task: title, parent_title, description, hours, iteration (ver adapters/azure.py).
    """
    iteration = task.get("iteration") or get_iteration()
    parent_ids = _find_by_title(task["parent_title"], iteration, only_tasks=False)
    if not parent_ids:
        raise RuntimeError(
            f"No existe el padre '{task['parent_title']}' en {iteration}."
        )
    return upsert_child_task(parent_ids[0], task)

def upsert_child_task(parent_id, task):
    """Una sola Task hija por (padre, iteración): la crea o, si existe, suma horas y
    concatena la descripción. Devuelve (id, 'creada' | 'actualizada').
    task: title, description, hours, iteration.
    """
    iteration = task.get("iteration") or get_iteration()
    existing = None
    task_ids = _find_by_title(task["title"], iteration, only_tasks=True)
    if task_ids:
        existing = next(
            (i for i in _fetch_batch(task_ids) if _parent_id(i) == parent_id), None
        )

    if existing is None:
        return _create_task(parent_id, {**task, "iteration": iteration}), "creada"

    f = existing["fields"]
    horas = round(
        float(f.get("Microsoft.VSTS.Scheduling.CompletedWork") or 0) + float(task["hours"]), 2
    )
    body = []
    add_field(
        body, "System.Description",
        (f.get("System.Description") or "") + f"<div>{task.get('description', '')}</div>",
    )
    add_field(body, "Microsoft.VSTS.Scheduling.OriginalEstimate", horas)
    add_field(body, "Microsoft.VSTS.Scheduling.RemainingWork", "0")
    add_field(body, "Microsoft.VSTS.Scheduling.CompletedWork", horas)
    url = f"{AZURE_ENDPOINT}/_apis/wit/workitems/{existing['id']}?api-version=7.1"
    ado_patch_fetch(url, body, method="PATCH")
    print(f"✅ {existing['id']} actualizada: total {horas} h")
    return existing["id"], "actualizada"

def create_parent_task(parent=None):
    """Crea el Bug padre. Si no se pasa `parent`, lee parent_task.json (modo manual).

    parent: dict con title y opcionalmente assignedTo, description, fields, iteration.
    """
    if parent is None:
        with open(BASE_DIR / "parent_task.json", encoding="utf-8") as f:
            parent = json.load(f)["parent"]
    print(f"Creando: {parent.get('title')}")
    work_item_type = WORK_ITEM_TYPE
    url = (
        f"{AZURE_ENDPOINT}/_apis/wit/workitems/"
        f"${quote(work_item_type)}?api-version=7.1"
    )

    body = []
    add_field(body, "System.Title", parent.get("title"))
    add_field(body, "System.AreaPath", AREA)
    add_field(body, "System.IterationPath", parent.get("iteration") or get_iteration())
    add_field(body, "System.AssignedTo", parent.get("assignedTo"))
    if parent.get("description"):
        add_field(body, "System.Description", f"<div>{parent['description']}</div>")
    add_field(body, "Microsoft.VSTS.Common.Activity", config["activity"])
    #add_field(body, "Microsoft.VSTS.Scheduling.OriginalEstimate", parent.get("originalEstimate"))
    #add_field(body, "Microsoft.VSTS.Scheduling.RemainingWork", parent.get("remaining"))
    #add_field(body, "Microsoft.VSTS.Scheduling.CompletedWork", parent.get("completed"))
    add_field(body, "Custom.Sistema", config["sistema"])

    # Campos requeridos por el tipo (p.ej. Bug): Severity, Priority_B, etc.
    # Se definen en parent_task.json como "fields": {"<referenceName>": valor}
    # y el item puede sobreescribirlos.
    extra = {**config.get("fields", {}), **parent.get("fields", {})}
    for ref_name, value in extra.items():
        add_field(body, ref_name, value)

    created = ado_patch_fetch(url, body)
    print(f"✅ {created['id']} - {created['fields']['System.Title']}")
    return created["id"]
