"""Pruebas del dashboard con TestClient y gateways falsos (sin red, sin escribir en data/)."""
import re
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app.main import create_app
from dashboard.app.modules import horas
from dashboard.app.modules.horas import router as horas_router
from dashboard.app.modules.horas.service import HorasService
from timetrack.agent import ExtraccionError
from timetrack.models import Plan

S22 = r"ST_Canales_CX\2026\Sprint 2026.22"


def plan_de(descripcion_libre="Soporte a QA"):
    return Plan.model_validate({"dias": [{"fecha": "2026-10-29", "actividades": [
        {"descripcion": descripcion_libre, "horas": 4},
        {"descripcion": "Revisión SINPE", "horas": 4, "incidente": "100001273"},
    ]}]})


class FakeAzure:
    def __init__(self, existentes=None):
        self.existentes = {"100001273": 988523} if existentes is None else existentes
        self.children, self.grouped, self.bugs = [], [], []

    def iteration_for(self, fecha):
        return S22

    def find_incident(self, inc):
        return self.existentes.get(inc)

    def create_bug(self, titulo, iteration):
        self.bugs.append(titulo)
        return 1

    def upsert_child(self, parent_id, task):
        self.children.append((parent_id, task["hours"]))
        return 900, "creada"

    def upsert_grouped(self, task):
        self.grouped.append(task["hours"])
        return 995051, "actualizada"

    def workitem_url(self, ref):
        return f"https://dev.example/_workitems/edit/{ref}"

    def sprint_tasks(self, sprint):
        if str(sprint) == "99":
            raise ValueError("No se encontró el sprint 99 entre las iteraciones del equipo.")
        return {"sprint": "Sprint 2026.22", "totales": {"tareas": 1, "estimado": 4.0, "completado": 4.0, "restante": 0.0},
                "grupos": [{"padre": {"id": 7, "titulo": "DEV - Revisión <SOA>", "tipo": "Bug"},
                            "tareas": [{"id": 8, "titulo": "Tarea 8", "descripcion": "Hice X y Z", "estado": "Closed",
                                        "estimado": 4.0, "completado": 4.0, "restante": 0.0}]}]}


class FakeSiges:
    def __init__(self):
        self.enviados = []

    def send_day(self, fecha, tareas, cerrar_dia=False):
        self.enviados.append(fecha)
        return 200, "ok"


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.azure, self.siges = FakeAzure(), FakeSiges()
        self.plan = plan_de()
        self.install_service()
        self.app = create_app(modules=[horas.module])
        self.client = TestClient(self.app, base_url="http://localhost")
        self.token = self.app.state.csrf_token
        self._orig = horas_router.service
        self.ledger_path = d / "ledger.json"

    def install_service(self):
        d = Path(self.tmp.name)
        self._orig_service = horas_router.service
        horas_router.service = HorasService(
            parse=lambda texto, progress=None: self.plan,
            azure_factory=lambda: self.azure, siges_factory=lambda: self.siges,
            catalog_path=d / "catalog.json", ledger_path=d / "ledger.json",
        )

    def tearDown(self):
        horas_router.service = self._orig_service
        self.tmp.cleanup()

    # --- helpers ---
    def post(self, url, data=None, **kw):
        headers = {"X-CSRF-Token": self.token, **kw.pop("headers", {})}
        return self.client.post(url, data=data or {}, headers=headers, **kw)

    def esperar(self, html):
        """Sigue el polling del job hasta que termina y devuelve el HTML final."""
        for _ in range(100):
            m = re.search(r"/horas/jobs/(\w+)", html)
            if "aria-busy" not in html or not m:
                return html
            time.sleep(0.05)
            html = self.client.get(f"/horas/jobs/{m.group(1)}").text
        self.fail("El job no terminó a tiempo")

    def interpretar(self):
        html = self.esperar(self.post("/horas/interpretar", {"prosa": "x"}).text)
        m = re.search(r'name="preview_id" value="(\w+)"', html)
        return html, (m.group(1) if m else None)

    # --- páginas ---
    def test_portada_lista_el_modulo(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Reporte de horas", r.text)
        self.assertIn("Aún no hay envíos registrados.", r.text)

    def test_tema_claro_oscuro_e_iconos_locales(self):
        home = self.client.get("/").text
        self.assertIn("data-theme-toggle", home)          # botón de tema en el menú
        self.assertIn('localStorage.getItem("theme")', home)  # aplica la preferencia guardada
        self.assertIn("bi-clock-history", home)           # icono del módulo en el menú/tarjeta
        for ruta in ("/static/vendor/bootstrap-icons/bootstrap-icons.min.css",
                     "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
                     "/static/app.css"):
            self.assertEqual(self.client.get(ruta).status_code, 200, ruta)
        css = self.client.get("/static/app.css").text
        self.assertIn('[data-bs-theme="dark"]', css)

    def test_mi_sprint_muestra_tareas_con_padre_estado_y_horas(self):
        self.assertIn("Mi sprint", self.client.get("/horas/").text)  # pestaña
        self.assertEqual(self.client.get("/horas/sprint").status_code, 200)
        r = self.client.get("/horas/sprint/tareas", params={"numero": "22"})
        self.assertEqual(r.status_code, 200)
        for esperado in ("Sprint 2026.22", "Tarea 8", "Hice X", "Closed", "4,0", "_workitems/edit/8", "_workitems/edit/7"):
            self.assertIn(esperado, r.text)
        self.assertIn("DEV - Revisión &lt;SOA&gt;", r.text)  # el padre aparece y se escapa

    def test_mi_sprint_errores_se_muestran_sin_romper(self):
        self.assertIn("Escriba el número", self.client.get("/horas/sprint/tareas", params={"numero": " "}).text)
        r = self.client.get("/horas/sprint/tareas", params={"numero": "99"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("No se encontró el sprint 99", r.text)

    def test_no_expone_documentacion_de_la_api(self):
        self.assertEqual(self.client.get("/docs").status_code, 404)
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)

    # --- seguridad ---
    def test_post_sin_token_csrf_se_rechaza(self):
        r = self.client.post("/horas/interpretar", data={"prosa": "x"})
        self.assertEqual(r.status_code, 403)

    def test_post_con_origen_ajeno_se_rechaza(self):
        r = self.post("/horas/interpretar", {"prosa": "x"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_host_ajeno_se_rechaza(self):
        r = self.client.get("/", headers={"Host": "evil.example"})
        self.assertEqual(r.status_code, 400)

    # --- flujo principal ---
    def test_interpretar_muestra_preview_sin_escribir_nada(self):
        html, pid = self.interpretar()
        self.assertIn("Vista previa", html)
        self.assertIn("DEV - Revisión SOA", html)
        self.assertIn("DEV - Joseph Ramirez", html)
        self.assertIsNotNone(pid)
        self.assertEqual((self.azure.children, self.azure.grouped, self.siges.enviados), ([], [], []))
        self.assertFalse((Path(self.tmp.name) / "ledger.json").exists())

    def test_enviar_escribe_y_registra_en_el_ledger(self):
        _, pid = self.interpretar()
        html = self.esperar(self.post("/horas/enviar", {"preview_id": pid}).text)
        self.assertIn("Envío completado", html)
        self.assertIn("https://dev.example/_workitems/edit/900", html)
        self.assertEqual(self.azure.children, [(988523, 4)])
        self.assertEqual(self.azure.grouped, [4])
        self.assertEqual(self.siges.enviados, ["2026-10-29"])
        self.assertTrue((Path(self.tmp.name) / "ledger.json").exists())

    def test_la_vista_previa_no_se_puede_enviar_dos_veces(self):
        _, pid = self.interpretar()
        self.esperar(self.post("/horas/enviar", {"preview_id": pid}).text)
        segundo = self.post("/horas/enviar", {"preview_id": pid}).text
        self.assertIn("no existe o ya se envió", segundo)
        self.assertEqual(len(self.azure.children), 1)

    def test_preview_id_desconocido(self):
        html = self.post("/horas/enviar", {"preview_id": "inventado"}).text
        self.assertIn("no existe o ya se envió", html)
        self.assertEqual(self.siges.enviados, [])

    def test_reinterpretar_despues_de_enviar_no_duplica(self):
        _, pid = self.interpretar()
        self.esperar(self.post("/horas/enviar", {"preview_id": pid}).text)
        html, _ = self.interpretar()
        self.assertIn("No hay nada pendiente de enviar", html)

    def test_incidente_nuevo_exige_titulo(self):
        self.azure.existentes = {}
        html, pid = self.interpretar()
        self.assertIn("titulo__100001273", html)
        sin = self.post("/horas/enviar", {"preview_id": pid}).text
        self.assertIn("Falta el título del Bug", sin)
        self.assertEqual(self.azure.bugs, [])
        con = self.esperar(self.post("/horas/enviar",
                                     {"preview_id": pid, "titulo__100001273": "Falla SINPE"}).text)
        self.assertIn("Envío completado", con)
        self.assertEqual(self.azure.bugs, ["100001273 - Falla SINPE"])

    def test_error_de_interpretacion_se_muestra(self):
        def falla(texto, progress=None):
            raise ExtraccionError("29-10-2026: sin horas válidas")
        horas_router.service.parse = falla
        html = self.esperar(self.post("/horas/interpretar", {"prosa": "x"}).text)
        self.assertIn("No se pudo continuar", html)
        self.assertIn("sin horas válidas", html)

    def test_dia_que_no_suma_8_horas_se_muestra_como_error(self):
        self.plan.dias[0].actividades[0].horas = 1
        html = self.esperar(self.post("/horas/interpretar", {"prosa": "x"}).text)
        self.assertIn("No se pudo continuar", html)
        self.assertIn("se esperaban 8.0 h", html)

    def test_prosa_vacia(self):
        self.assertIn("Pegue el reporte", self.post("/horas/interpretar", {"prosa": "  "}).text)

    def test_html_del_reporte_se_escapa(self):
        self.plan = plan_de("<script>alert(1)</script>")
        html, _ = self.interpretar()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_historial_normaliza_refs_antiguas_en_formato_tupla(self):
        from timetrack.ledger import Ledger
        led = Ledger(Path(self.tmp.name) / "ledger.json")
        led.add("k1", sistema="azure", ref="(997084, 'actualizada')")
        led.add("k2", sistema="azure", ref="995051")
        h = self.client.get("/horas/historial").text
        self.assertIn("work item 997084", h)
        self.assertIn("work item 995051", h)
        self.assertNotIn("actualizada", h)

    def test_historial_y_resumen_reflejan_los_envios(self):
        _, pid = self.interpretar()
        self.esperar(self.post("/horas/enviar", {"preview_id": pid}).text)
        h = self.client.get("/horas/historial").text
        self.assertIn("azure", h)
        self.assertIn("2026-10-29", h)
        self.assertIn("100001273", h)
        self.assertIn("2 actividad(es) en Azure, 1 día(s) en SIGES", self.client.get("/").text)

    def test_historial_calendario_agrupa_por_dia_y_valida_parametros(self):
        from dashboard.app.modules.horas.service import _calendario
        rows = [   # `dia` = día de la tarea (puede diferir del de envío)
            {"enviado": "2026-10-29 16:05:00", "sistema": "siges", "detalle": "Día completo", "dia": "2026-10-29", "sin_fecha": False},
            {"enviado": "2026-10-29 16:04:10", "sistema": "azure", "detalle": "work item 7", "dia": "2026-10-29", "sin_fecha": False},
            {"enviado": "2026-11-02 09:00:00", "sistema": "azure", "detalle": "work item 5", "dia": "2026-10-03", "sin_fecha": False},
        ]
        cal = _calendario(rows, "2026-10", None)
        self.assertEqual((cal["titulo"], cal["anterior"], cal["siguiente"]), ("octubre 2026", "2026-09", "2026-11"))
        self.assertTrue(all(len(sem) == 7 for sem in cal["semanas"]))
        self.assertEqual(cal["semanas"][0][0]["iso"][:4], "2026")          # la semana empieza en lunes
        celdas = {c["iso"]: c for sem in cal["semanas"] for c in sem}
        self.assertEqual((celdas["2026-10-29"]["azure"], celdas["2026-10-29"]["siges"]), (1, 1))
        self.assertEqual(cal["detalle"]["iso"], "2026-10-29")             # por defecto, el día más reciente con envíos
        self.assertEqual(_calendario(rows, "2026-10", "2026-10-03")["detalle"]["envios"][0]["detalle"], "work item 5")
        for malo in ("basura", "2026-13", "9999-01", "0000-01", ""):         # nunca rompe: cae al mes actual
            self.assertEqual(len(_calendario(rows, malo, None)["semanas"][0]), 7)
        self.assertEqual(self.client.get("/horas/historial", params={"mes": "2026-10", "dia": "x"}).status_code, 200)

    def test_historial_usa_la_fecha_de_la_tarea_y_cae_al_envio_si_falta(self):
        from dashboard.app.modules.horas.service import _calendario
        hoy = date.today()
        antiguo = {"enviado": f"{hoy:%Y-%m-%d} 10:00:00", "sistema": "azure", "detalle": "work item 1",
                   "dia": f"{hoy:%Y-%m-%d}", "sin_fecha": True}
        pasado = {"enviado": f"{hoy:%Y-%m-%d} 10:05:00", "sistema": "siges", "detalle": "Día completo",
                  "dia": "2020-03-15", "sin_fecha": False}
        cal = _calendario([pasado, antiguo], None, None)
        self.assertEqual(cal["mes"], f"{hoy:%Y-%m}")                       # el mes actual tiene envíos
        self.assertTrue(cal["detalle"]["envios"][0]["sin_fecha"])           # se marca como día de envío
        cal = _calendario([pasado], None, None)                            # el mes actual está vacío
        self.assertEqual((cal["mes"], cal["detalle"]["iso"]), ("2020-03", "2020-03-15"))
        self.assertEqual(_calendario([], None, None)["mes"], f"{hoy:%Y-%m}")   # sin ledger: el mes actual


if __name__ == "__main__":
    unittest.main()
