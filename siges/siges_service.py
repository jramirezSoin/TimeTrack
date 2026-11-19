"""Cliente de SIGES (WStareas.cfc): login y Grabar_Tareas.

Credenciales por variables de entorno: SIGES_USER y SIGES_PASS.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

CONFIG = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
URI = CONFIG["uri"]
TASK_FILE = Path(__file__).with_name("siges_task.json")

_session = None  # (id_session, cookie)


def _post(data, cookie=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(
        URI,
        data=urllib.parse.urlencode(data).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def login(username=None, password=None):
    """Inicia sesión y devuelve (status, body). Usa SIGES_USER/SIGES_PASS por defecto."""
    username = username or os.environ.get("SIGES_USER")
    password = password or os.environ.get("SIGES_PASS")
    if not username or not password:
        raise RuntimeError("Faltan las variables de entorno SIGES_USER y SIGES_PASS.")
    return _post({"UID": username, "method": "login", "PWD": password})


def _cookie_from(id_session):
    pares = {n.upper(): v[0] for n, v in parse_qs(id_session).items()}
    return "; ".join(f"{n}={v}" for n, v in pares.items())


def get_session(force=False):
    """Devuelve (id_session, cookie), iniciando sesión si hace falta."""
    global _session
    if _session is None or force:
        _, body = login()
        id_session = json.loads(body)["IDSESSION"]
        _session = (id_session, _cookie_from(id_session))
    return _session

def JSON_ListaTareas():
    """Devuelve la lista de tareas en formato JSON."""
    id_session, cookie = get_session()
    status, body = _post({"IDSESSION": id_session, "method": "JSON_ListaTareas"}, cookie=cookie)
    if status != 200:
        raise RuntimeError(f"Error al obtener ListaTareas: {status} {body}")
    return status, body


def grabar_tareas(tareas=None, fecha=None, cerrar_dia=False):
    """Envía tareas a SIGES.

    tareas: lista de dicts (ver siges_task.json) o None para leer siges_task.json.
    fecha: 'YYYY-MM-DD' o ISO completo; por defecto hoy.
    """
    if tareas is None:
        tareas = json.loads(TASK_FILE.read_text(encoding="utf-8"))["TAREAS"]
    if fecha is None:
        fecha = date.today().isoformat()
    if "T" not in fecha:
        fecha += "T00:00:00.000Z"

    def _enviar():
        id_session, cookie = get_session()
        return _post(
            {
                "IDSESSION": id_session,
                "method": "Grabar_Tareas",
                "cerrarDia": "false",#str(cerrar_dia).lower(),
                "Fecha": fecha,
                "Tareas": json.dumps({"TAREAS": tareas}, ensure_ascii=False),
            },
            cookie=cookie,
        )

    try:
        return _enviar()
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise
        get_session(force=True)  # sesión expirada: nuevo login y un reintento
        return _enviar()


if __name__ == "__main__":
    status, body = JSON_ListaTareas()
    print(status, body)
