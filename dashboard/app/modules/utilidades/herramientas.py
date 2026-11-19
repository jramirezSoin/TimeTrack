"""Herramientas de texto/datos (lógica pura, sin FastAPI). Los errores de entrada son ValueError con mensaje claro."""
from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime, timedelta, timezone
from xml.dom import minidom
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring as _safe_fromstring

MAX_BYTES = 1_000_000
ZONA_LOCAL = "America/Costa_Rica"
ZONAS_SUGERIDAS = ["America/Costa_Rica", "UTC", "America/Mexico_City", "America/Bogota", "America/New_York",
                   "America/Los_Angeles", "America/Sao_Paulo", "Europe/Madrid", "Europe/London"]


def _entrada(texto: str | None, nombre: str = "El texto") -> str:
    texto = (texto or "").strip()
    if not texto:
        raise ValueError(f"{nombre} está vacío.")
    if len(texto.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"{nombre} supera el máximo de {MAX_BYTES // 1000} KB.")
    return texto


# ───────────────────────────── JSON ─────────────────────────────
def _json(texto: str, nombre: str = "El JSON"):
    try:
        return json.loads(_entrada(texto, nombre))
    except json.JSONDecodeError as e:
        raise ValueError(f"{nombre} no es válido: {e.msg} (línea {e.lineno}, columna {e.colno}).") from None


def json_formatear(texto: str, minificar: bool = False) -> str:
    dato = _json(texto)
    if minificar:
        return json.dumps(dato, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(dato, ensure_ascii=False, indent=2)


def _ruta_json(base: str, clave) -> str:
    if isinstance(clave, int):
        return f"{base}[{clave}]"
    return f"{base}.{clave}" if re.fullmatch(r"[A-Za-z_]\w*", clave) else f'{base}["{clave}"]'


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _comparar_json(a, b, ruta: str, out: list[dict]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            r = _ruta_json(ruta, k)
            if k not in b:
                out.append({"ruta": r, "tipo": "eliminado", "antes": json.dumps(a[k], ensure_ascii=False), "despues": ""})
            elif k not in a:
                out.append({"ruta": r, "tipo": "agregado", "antes": "", "despues": json.dumps(b[k], ensure_ascii=False)})
            else:
                _comparar_json(a[k], b[k], r, out)
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            r = _ruta_json(ruta, i)
            if i >= len(b):
                out.append({"ruta": r, "tipo": "eliminado", "antes": json.dumps(a[i], ensure_ascii=False), "despues": ""})
            elif i >= len(a):
                out.append({"ruta": r, "tipo": "agregado", "antes": "", "despues": json.dumps(b[i], ensure_ascii=False)})
            else:
                _comparar_json(a[i], b[i], r, out)
    else:
        iguales = (a == b) and (type(a) is type(b) or (_num(a) and _num(b)))
        if not iguales:
            out.append({"ruta": ruta, "tipo": "cambiado", "antes": json.dumps(a, ensure_ascii=False),
                        "despues": json.dumps(b, ensure_ascii=False)})


def json_comparar(a: str, b: str) -> list[dict]:
    """Diferencias entre dos JSON por ruta; el orden de las claves no importa (el de las listas sí)."""
    out: list[dict] = []
    _comparar_json(_json(a, "El primer JSON"), _json(b, "El segundo JSON"), "$", out)
    return out


# ───────────────────────────── XML ─────────────────────────────
def _xml(texto: str, nombre: str = "El XML") -> ET.Element:
    """Parsea con defusedxml: sin DTD ni entidades (evita XXE y 'billion laughs')."""
    try:
        return _safe_fromstring(_entrada(texto, nombre), forbid_dtd=True)
    except ParseError as e:
        linea, col = e.position
        raise ValueError(f"{nombre} no es válido: {str(e.args[0]).split(':')[0]} (línea {linea}, columna {col + 1}).") from None
    except DefusedXmlException:
        raise ValueError(f"{nombre} contiene un DTD o entidades, que no se permiten por seguridad.") from None


def _sin_espacios(nodo) -> None:
    for hijo in list(nodo.childNodes):
        if hijo.nodeType == hijo.TEXT_NODE and not hijo.data.strip():
            nodo.removeChild(hijo)
        elif hijo.nodeType == hijo.ELEMENT_NODE:
            _sin_espacios(hijo)


def xml_formatear(texto: str, minificar: bool = False) -> str:
    """Indenta (o minifica) conservando los prefijos de namespace tal como vienen."""
    _xml(texto)  # valida y rechaza DTD/entidades antes de usar minidom
    dom = minidom.parseString(texto.strip().encode("utf-8"))
    _sin_espacios(dom)
    declaracion = texto.lstrip().startswith("<?xml")
    if minificar:
        return dom.toxml() if declaracion else dom.documentElement.toxml()
    salida = dom.toprettyxml(indent="  ")
    if not declaracion:
        salida = salida.split("\n", 1)[1]
    return salida.strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _comparar_xml(a: ET.Element, b: ET.Element, ruta: str, out: list[dict]) -> None:
    if a.tag != b.tag:
        out.append({"ruta": ruta, "tipo": "cambiado", "antes": f"<{_local(a.tag)}>", "despues": f"<{_local(b.tag)}>"})
        return
    for k in sorted(set(a.attrib) | set(b.attrib)):
        r = f"{ruta}/@{_local(k)}"
        if k not in b.attrib:
            out.append({"ruta": r, "tipo": "eliminado", "antes": a.attrib[k], "despues": ""})
        elif k not in a.attrib:
            out.append({"ruta": r, "tipo": "agregado", "antes": "", "despues": b.attrib[k]})
        elif a.attrib[k] != b.attrib[k]:
            out.append({"ruta": r, "tipo": "cambiado", "antes": a.attrib[k], "despues": b.attrib[k]})
    ta, tb = (a.text or "").strip(), (b.text or "").strip()
    if ta != tb:
        out.append({"ruta": ruta, "tipo": "cambiado", "antes": ta, "despues": tb})

    def con_indice(hijos):
        vistos: dict[str, int] = {}
        res = []
        for h in hijos:
            n = vistos[h.tag] = vistos.get(h.tag, 0) + 1
            res.append((f"{ruta}/{_local(h.tag)}[{n}]", h))
        return res

    ha, hb = con_indice(list(a)), con_indice(list(b))
    for i in range(max(len(ha), len(hb))):  # el orden de los elementos hermanos importa
        if i >= len(hb):
            out.append({"ruta": ha[i][0], "tipo": "eliminado", "antes": _resumen_xml(ha[i][1]), "despues": ""})
        elif i >= len(ha):
            out.append({"ruta": hb[i][0], "tipo": "agregado", "antes": "", "despues": _resumen_xml(hb[i][1])})
        else:
            _comparar_xml(ha[i][1], hb[i][1], ha[i][0], out)


def _resumen_xml(el: ET.Element) -> str:
    t = (el.text or "").strip()
    return t if t and not len(el) else f"<{_local(el.tag)}> …"


def xml_comparar(a: str, b: str) -> list[dict]:
    """Diferencias entre dos XML (namespaces resueltos, espacios entre etiquetas ignorados)."""
    ra, rb = _xml(a, "El primer XML"), _xml(b, "El segundo XML")
    out: list[dict] = []
    _comparar_xml(ra, rb, f"/{_local(ra.tag)}[1]", out)
    return out


# ───────────────────────────── Base64 ─────────────────────────────
def b64_codificar(texto: str, urlsafe: bool = False) -> str:
    if texto is None or texto == "":
        raise ValueError("El texto está vacío.")
    datos = texto.encode("utf-8")
    if len(datos) > MAX_BYTES:
        raise ValueError(f"El texto supera el máximo de {MAX_BYTES // 1000} KB.")
    return (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(datos).decode("ascii")


def _b64_bytes(texto: str, urlsafe: bool) -> bytes:
    s = re.sub(r"\s+", "", _entrada(texto, "El Base64")).rstrip("=")
    alfabeto = r"[A-Za-z0-9\-_]*" if urlsafe else r"[A-Za-z0-9+/]*"
    if not re.fullmatch(alfabeto, s):
        raise ValueError("El Base64 no es válido: tiene caracteres fuera del alfabeto"
                         + (" URL-safe (use - y _)." if urlsafe else " estándar (use + y /)."))
    s += "=" * (-len(s) % 4)
    try:
        return (base64.urlsafe_b64decode if urlsafe else base64.b64decode)(s)
    except (binascii.Error, ValueError):
        raise ValueError("El Base64 no es válido (longitud incorrecta).") from None


def b64_decodificar(texto: str, urlsafe: bool = False) -> dict:
    datos = _b64_bytes(texto, urlsafe)
    try:
        return {"texto": datos.decode("utf-8"), "utf8": True, "bytes": len(datos), "hex": ""}
    except UnicodeDecodeError:
        return {"texto": datos.decode("utf-8", errors="replace"), "utf8": False, "bytes": len(datos),
                "hex": datos[:64].hex(" ")}


# ───────────────────────────── JWT ─────────────────────────────
def _jwt_parte(parte: str, nombre: str) -> dict:
    try:
        datos = base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4))
        obj = json.loads(datos.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise ValueError(f"El {nombre} del JWT no es Base64URL con JSON válido.") from None
    if not isinstance(obj, dict):
        raise ValueError(f"El {nombre} del JWT debe ser un objeto JSON.")
    return obj


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _desde_epoch(segundos: float) -> datetime:
    """Segundos Unix -> datetime UTC. No usa fromtimestamp (en Windows falla con fechas anteriores a 1970)."""
    try:
        return _EPOCH + timedelta(seconds=segundos)
    except (OverflowError, ValueError):
        raise ValueError("El timestamp está fuera del rango de fechas soportado.") from None


def _iso(dt: datetime, zona: str) -> str:
    return dt.astimezone(ZoneInfo(zona)).isoformat(timespec="seconds")


def jwt_decodificar(token: str, ahora: datetime | None = None) -> dict:
    """Decodifica encabezado y payload. NO verifica la firma."""
    t = _entrada(token, "El JWT")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    partes = t.split(".")
    if len(partes) != 3:
        raise ValueError("Un JWT tiene tres partes separadas por puntos (encabezado.payload.firma).")
    encabezado, payload = _jwt_parte(partes[0], "encabezado"), _jwt_parte(partes[1], "payload")
    ahora = ahora or datetime.now(timezone.utc)
    fechas, expirado, aun_no = [], None, None
    for claim, etiqueta in (("iat", "Emitido"), ("nbf", "Válido desde"), ("exp", "Expira")):
        v = payload.get(claim)
        if _num(v):
            try:
                dt = _desde_epoch(v)
            except ValueError:
                continue
            fechas.append((f"{etiqueta} ({claim})", f"{_iso(dt, 'UTC')}  ·  {_iso(dt, ZONA_LOCAL)}"))
            if claim == "exp":
                expirado = dt <= ahora
            if claim == "nbf":
                aun_no = dt > ahora
    return {"encabezado": encabezado, "payload": payload, "firma": bool(partes[2]), "fechas": fechas,
            "expirado": expirado, "aun_no_valido": aun_no}


# ───────────────────────────── Fechas y timestamps ─────────────────────────────
def _zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo((nombre or "").strip())
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f"Zona horaria desconocida: {nombre!r} (ejemplo: America/Costa_Rica).") from None


_FORMATOS = ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y")


def _parse_fecha(texto: str, zona: ZoneInfo) -> datetime:
    """ISO 8601 o dd-mm-aaaa [HH:MM[:SS]]. Sin desplazamiento explícito se asume `zona`."""
    t = _entrada(texto, "La fecha")
    dt = None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        for fmt in _FORMATOS:
            try:
                dt = datetime.strptime(t, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise ValueError(f"Fecha no reconocida: {t!r}. Use ISO 8601 (2026-11-06T14:30:00) o dd-mm-aaaa [hh:mm[:ss]].")
    if dt.tzinfo is None:
        if dt.replace(tzinfo=zona, fold=0).utcoffset() != dt.replace(tzinfo=zona, fold=1).utcoffset():
            raise ValueError("Esa hora local es ambigua o no existe en la zona por el cambio de horario; "
                             "indique el desplazamiento (por ejemplo -06:00).")
        dt = dt.replace(tzinfo=zona)
    return dt


def _a_epoch(dt: datetime) -> tuple[int, int]:
    ms = round(dt.timestamp() * 1000)
    return ms // 1000, ms


def timestamp_a_fecha(valor: str, unidad: str = "auto") -> list[tuple[str, str]]:
    """Unix timestamp -> fecha. `unidad`: 'auto' (>= 1e11 se toma como ms), 's' o 'ms'."""
    t = _entrada(valor, "El timestamp")
    try:
        n = float(t)
    except ValueError:
        raise ValueError(f"El timestamp debe ser numérico (ejemplo: 1730000000): {t!r}.") from None
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError("El timestamp no es un número válido.")
    if unidad not in ("auto", "s", "ms"):
        raise ValueError("La unidad debe ser auto, s o ms.")
    en_ms = unidad == "ms" or (unidad == "auto" and abs(n) >= 1e11)
    segundos = n / 1000 if en_ms else n
    dt = _desde_epoch(segundos)
    s, ms = _a_epoch(dt)
    return [
        ("Unidad interpretada", "milisegundos" if en_ms else "segundos"),
        ("Segundos", str(s)),
        ("Milisegundos", str(ms)),
        ("UTC", _iso(dt, "UTC")),
        ("Costa Rica", _iso(dt, ZONA_LOCAL)),
    ]


def fecha_a_timestamp(texto: str, zona: str = ZONA_LOCAL) -> list[tuple[str, str]]:
    z = _zona(zona)
    dt = _parse_fecha(texto, z)
    s, ms = _a_epoch(dt)
    return [
        ("Interpretada como", dt.isoformat(timespec="seconds")),
        ("Segundos", str(s)),
        ("Milisegundos", str(ms)),
        ("UTC", _iso(dt, "UTC")),
    ]


def fecha_convertir(texto: str, origen: str = ZONA_LOCAL, destino: str = "UTC") -> list[tuple[str, str]]:
    zo, zd = _zona(origen), _zona(destino)
    dt = _parse_fecha(texto, zo)
    d = dt.astimezone(zd)
    return [
        (f"En {origen}", dt.astimezone(zo).isoformat(timespec="seconds")),
        (f"En {destino}", d.isoformat(timespec="seconds")),
        ("Formato dd-mm-aaaa", d.strftime("%d-%m-%Y %H:%M:%S")),
        ("Desplazamiento", d.strftime("%z")[:3] + ":" + d.strftime("%z")[3:]),
    ]
