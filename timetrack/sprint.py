"""Consulta de mis tareas por sprint: lógica pura (sin red) usada por el gateway de Azure."""
from __future__ import annotations

import html
import re
from datetime import date

_ENTRADA_RE = re.compile(r"^(?:sprint\s*)?(?:(\d{4})[.\-/])?(\d{1,3})$", re.IGNORECASE)
_NOMBRE_RE = re.compile(r"(\d{4})\.(\d+)\s*$")


def parse_sprint(texto) -> tuple[int | None, int]:
    """'22', 'Sprint 22', '2026.22' o 'Sprint 2026.22' -> (año | None, número)."""
    m = _ENTRADA_RE.match(str(texto or "").strip())
    if not m:
        raise ValueError(f"Sprint inválido: {texto!r}. Use el número (22) o año.número (2026.22).")
    anio, numero = m.groups()
    return (int(anio) if anio else None), int(numero)


def elegir_iteracion(iteraciones: list[dict], anio: int | None, numero: int, hoy: date | None = None) -> dict:
    """Iteración del equipo cuyo nombre termina en 'AAAA.número'.

    Sin año, se prefiere el del año actual; si no existe, el más reciente que tenga ese número.
    """
    candidatas = []
    for it in iteraciones:
        m = _NOMBRE_RE.search(it.get("name") or "")
        if m and int(m.group(2)) == numero and (anio is None or int(m.group(1)) == anio):
            candidatas.append((int(m.group(1)), it))
    if not candidatas:
        etiqueta = f"{anio}.{numero}" if anio else str(numero)
        raise ValueError(f"No se encontró el sprint {etiqueta} entre las iteraciones del equipo.")
    actual = (hoy or date.today()).year
    for a, it in candidatas:
        if a == actual:
            return it
    return max(candidatas, key=lambda c: c[0])[1]


def html_a_texto(valor: str | None) -> str:
    """Descripción de Azure (HTML) a texto plano con saltos de línea razonables."""
    if not valor:
        return ""
    t = re.sub(r"<\s*br\s*/?>|</\s*(div|p|li|tr|h\d)\s*>", "\n", valor, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    lineas = [ln.strip() for ln in t.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def _horas(v) -> float:
    return round(float(v or 0), 2)


def agrupar_por_padre(items: list[dict], padres: list[dict]) -> list[dict]:
    """Solo Tasks, agrupadas por su padre (los sin padre al final), con descripción en texto plano."""
    titulos = {p["id"]: p for p in padres}
    grupos: dict[int | None, dict] = {}
    for it in sorted((i for i in items if i.get("type") == "Task"), key=lambda i: i["id"]):
        pid = it.get("parentId")
        if pid not in grupos:
            p = titulos.get(pid) or {}
            grupos[pid] = {
                "padre": {"id": pid, "titulo": p.get("title") or "", "tipo": p.get("type") or ""} if pid else None,
                "tareas": [],
            }
        grupos[pid]["tareas"].append({
            "id": it["id"],
            "titulo": it.get("title") or "",
            "descripcion": html_a_texto(it.get("description")),
            "estado": it.get("state") or "",
            "estimado": _horas(it.get("estimated")),
            "completado": _horas(it.get("completed")),
            "restante": _horas(it.get("remaining")),
        })
    return sorted(grupos.values(), key=lambda g: (g["padre"] is None, g["padre"]["titulo"].lower() if g["padre"] else ""))


def totales(grupos: list[dict]) -> dict:
    ts = [t for g in grupos for t in g["tareas"]]
    return {
        "tareas": len(ts),
        "estimado": round(sum(t["estimado"] for t in ts), 2),
        "completado": round(sum(t["completado"] for t in ts), 2),
        "restante": round(sum(t["restante"] for t in ts), 2),
    }
