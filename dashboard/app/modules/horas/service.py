"""Lógica del módulo de horas: envuelve el núcleo `timetrack` (no depende de FastAPI)."""
from __future__ import annotations

import calendar
import re
import threading
import uuid
from datetime import date, datetime, timedelta

from timetrack.catalog import Catalog
from timetrack.ledger import Ledger
from timetrack.pipeline import Preview, Result, build_preview, execute


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre"]
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _calendario(rows: list[dict], mes: str | None, dia: str | None) -> dict:
    """Cuadrícula mensual (lunes primero) con las actividades de cada día, según la fecha de la tarea."""
    hoy = date.today()
    por_dia: dict[str, list[dict]] = {}
    for r in rows:                                    # `rows` ya viene del más reciente al más antiguo
        por_dia.setdefault(r["dia"], []).append(
            {"enviado": r["enviado"][:16], "sistema": r["sistema"], "detalle": r["detalle"],
             "sin_fecha": r["sin_fecha"]})
    try:
        anio, m = (int(x) for x in (mes or "").split("-"))
        if not 2000 <= anio <= 2100:
            raise ValueError("año fuera de rango")
        primero = date(anio, m, 1)
    except ValueError:
        # Sin mes válido: el actual si tiene envíos; si no, el del día más reciente que haya en el ledger.
        primero = hoy.replace(day=1)
        if por_dia and not any(k.startswith(primero.strftime("%Y-%m")) for k in por_dia):
            try:
                primero = date.fromisoformat(max(por_dia)).replace(day=1)
            except ValueError:
                pass

    def titulo_dia(d: date) -> str:
        return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]}"

    semanas = []
    for semana in calendar.Calendar(firstweekday=0).monthdatescalendar(primero.year, primero.month):
        fila = []
        for d in semana:
            envios = por_dia.get(d.isoformat(), [])
            azure = sum(1 for e in envios if e["sistema"] == "azure")
            siges = sum(1 for e in envios if e["sistema"] == "siges")
            if envios:
                partes = ([f"{azure} a Azure"] if azure else []) + ([f"{siges} a SIGES"] if siges else [])
                etiqueta = f"{titulo_dia(d)}: {', '.join(partes) or str(len(envios)) + ' envío(s)'}"
            else:
                etiqueta = f"{titulo_dia(d)}: sin envíos"
            fila.append({"iso": d.isoformat(), "num": d.day, "en_mes": d.month == primero.month, "hoy": d == hoy,
                         "azure": azure, "siges": siges, "total": len(envios), "etiqueta": etiqueta})
        semanas.append(fila)

    # Día elegido: el de la URL si cae en este mes; si no, el más reciente del mes con envíos.
    prefijo = primero.strftime("%Y-%m")
    con_envios = sorted((k for k in por_dia if k.startswith(prefijo)), reverse=True)
    elegido = dia if dia in por_dia and (dia or "").startswith(prefijo) else (con_envios[0] if con_envios else None)
    detalle = None
    if elegido:
        d = date.fromisoformat(elegido)
        detalle = {"iso": elegido, "titulo": titulo_dia(d), "envios": por_dia[elegido]}

    anterior = (primero - timedelta(days=1)).replace(day=1)
    siguiente = (primero + timedelta(days=32)).replace(day=1)
    return {
        "titulo": f"{_MESES[primero.month - 1]} {primero.year}", "mes": prefijo,
        "anterior": anterior.strftime("%Y-%m"), "siguiente": siguiente.strftime("%Y-%m"),
        "es_hoy": prefijo == hoy.strftime("%Y-%m"), "hoy_mes": hoy.strftime("%Y-%m"),
        "dias": [(n, n[:3]) for n in _DIAS], "semanas": semanas,
        "hay_envios": bool(con_envios), "detalle": detalle,
    }


def _real_parse(texto, progress=None):
    from timetrack.agent import parse_prose
    return parse_prose(texto, progress=progress)


def _real_azure():
    from timetrack.gateways import AzureGateway
    return AzureGateway()


def _real_siges():
    from timetrack.gateways import SigesGateway
    return SigesGateway()


class HorasService:
    MAX_PREVIEWS = 20

    def __init__(self, *, parse=None, azure_factory=None, siges_factory=None,
                 catalog_path=None, ledger_path=None):
        self.parse = parse or _real_parse
        self._azure_factory = azure_factory or _real_azure
        self._siges_factory = siges_factory or _real_siges
        self.catalog_path = catalog_path
        self.ledger_path = ledger_path
        self._azure = None
        self._siges = None
        self._previews: dict[str, Preview] = {}
        self._lock = threading.Lock()
        self.send_lock = threading.Lock()

    # --- dependencias (los gateways se crean al primer uso) ---
    @property
    def azure(self):
        if self._azure is None:
            self._azure = self._azure_factory()
        return self._azure

    @property
    def siges(self):
        if self._siges is None:
            self._siges = self._siges_factory()
        return self._siges

    def catalog(self) -> Catalog:
        return Catalog(self.catalog_path) if self.catalog_path else Catalog()

    def ledger(self) -> Ledger:
        return Ledger(self.ledger_path) if self.ledger_path else Ledger()

    # --- interpretar -> preview ---
    def interpretar(self, job, texto: str) -> str:
        """Prosa -> plan -> preview. Devuelve el id del preview guardado."""
        job.emit("Interpretando el reporte...")
        plan = self.parse(texto, progress=job.emit)
        job.emit("Consultando Azure (sprints e incidentes) y el ledger...")
        preview = build_preview(plan, catalog=self.catalog(), ledger=self.ledger(), azure=self.azure)
        pid = uuid.uuid4().hex
        with self._lock:
            self._previews[pid] = preview
            while len(self._previews) > self.MAX_PREVIEWS:
                self._previews.pop(next(iter(self._previews)))
        job.emit("Vista previa lista.")
        return pid

    def get_preview(self, pid: str) -> Preview | None:
        with self._lock:
            return self._previews.get(pid)

    def take_preview(self, pid: str) -> Preview | None:
        """Obtiene y consume el preview: cada vista previa se envía una sola vez."""
        with self._lock:
            return self._previews.pop(pid, None)

    # --- enviar ---
    def enviar(self, job, preview: Preview, titles: dict[str, str]) -> Result:
        if not self.send_lock.acquire(blocking=False):
            raise RuntimeError("Ya hay un envío en curso; espere a que termine.")
        try:
            job.emit("Enviando a Azure DevOps y SIGES...")
            result = execute(
                preview, catalog=self.catalog(), ledger=self.ledger(),
                azure=self.azure, siges=self.siges,
                ask_title=lambda inc: titles.get(inc, ""), out=job.emit,
            )
            job.emit(f"Terminado con {len(result.errors)} error(es).")
            return result
        finally:
            self.send_lock.release()

    def workitem_url(self, ref):
        make = getattr(self.azure, "workitem_url", None)
        return make(ref) if make else None

    # --- mis tareas de un sprint ---
    def sprint(self, numero: str) -> dict:
        """Mis Tasks del sprint indicado, agrupadas por padre, con enlaces a Azure."""
        datos = self.azure.sprint_tasks(numero)
        for g in datos["grupos"]:
            if g["padre"]:
                g["padre"]["url"] = self.workitem_url(g["padre"]["id"])
            for t in g["tareas"]:
                t["url"] = self.workitem_url(t["id"])
        return datos

    # --- lectura (portada e historial) ---
    def summary(self) -> list[str]:
        entries = self.ledger().entries()
        desde = datetime.now() - timedelta(days=7)
        recientes = [e for e in entries.values() if datetime.fromisoformat(e["enviado"]) >= desde]
        az = sum(1 for e in recientes if e.get("sistema") == "azure")
        sg = sum(1 for e in recientes if e.get("sistema") == "siges")
        lines = [f"Últimos 7 días: {az} actividad(es) en Azure, {sg} día(s) en SIGES."]
        if entries:
            lines.append("Último envío: " + max(e["enviado"] for e in entries.values()).replace("T", " "))
        else:
            lines.append("Aún no hay envíos registrados.")
        return lines

    def historial(self, limit: int = 100, mes: str | None = None, dia: str | None = None) -> dict:
        rows = []
        for e in self.ledger().entries().values():
            if e.get("sistema") == "azure":
                # Entradas antiguas guardaron la tupla "(997084, 'actualizada')": se toma solo el id.
                m = re.search(r"\d+", str(e.get("ref", "")))
                detalle = f"work item {m.group(0)}" if m else "work item"
            else:
                detalle = "Día completo"
            # Día de la tarea; las entradas de Azure anteriores a que el ledger guardara la fecha usan la del envío.
            fecha = str(e.get("fecha") or "")
            tiene = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha))
            rows.append({"enviado": e["enviado"].replace("T", " "), "sistema": e.get("sistema", "?"),
                         "detalle": detalle, "dia": fecha if tiene else e["enviado"][:10], "sin_fecha": not tiene})
        rows.sort(key=lambda r: r["enviado"], reverse=True)
        incidentes = [
            {"incidente": k, "azure_id": v["azure_id"], "titulo": v.get("titulo") or ""}
            for k, v in sorted(self.catalog().incidents().items())
        ]
        return {"envios": rows[:limit], "incidentes": incidentes, "cal": _calendario(rows, mes, dia)}
