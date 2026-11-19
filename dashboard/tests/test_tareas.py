"""Pruebas del módulo de tareas (TestClient, servicio temporal y Azure falso; sin red ni data/)."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app.main import create_app
from dashboard.app.modules import tareas
from dashboard.app.modules.tareas import router as tareas_router
from dashboard.app.modules.tareas.service import TareasService
from timetrack.tareas import Estado, TaskStore


class FakeAzure:
    def __init__(self, existentes=None, falla=False):
        self.existentes = existentes or {}
        self.falla = falla
        self.bugs = []

    def find_incident(self, inc):
        if self.falla:
            raise RuntimeError("Azure caído")
        return self.existentes.get(inc)

    def create_bug(self, titulo, iteration):
        self.bugs.append(titulo)
        return 321


class TareasDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.azure = FakeAzure()
        self.store_path = d / "tareas.json"
        self._orig = tareas_router.service
        tareas_router.service = TareasService(
            store_path=self.store_path, catalog_path=d / "catalog.json", azure_factory=lambda: self.azure)
        self.app = create_app(modules=[tareas.module])
        self.client = TestClient(self.app, base_url="http://localhost")
        self.token = self.app.state.csrf_token

    def tearDown(self):
        tareas_router.service = self._orig
        self.tmp.cleanup()

    def post(self, url, data=None, **kw):
        return self.client.post(url, data=data or {}, headers={"X-CSRF-Token": self.token}, **kw)

    def nueva(self, titulo, incidente=""):
        return self.post("/tareas/nueva", {"titulo": titulo, "incidente": incidente})

    def estado_de(self, id):
        return TaskStore(self.store_path).obtener(id).estado

    # --- páginas ---
    def test_portada_y_menu_listan_tareas(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('href="/tareas/"', r.text)
        self.assertIn("0 pendiente(s)", r.text)

    def test_pagina_vacia_muestra_columnas_y_basurero(self):
        r = self.client.get("/tareas/")
        self.assertEqual(r.status_code, 200)
        for esperado in ("Pendientes", "En proceso", "Entregadas", 'data-drop="cerrada"', "/static/tareas.js"):
            self.assertIn(esperado, r.text)
        self.assertNotIn("postit-texto", r.text)

    # --- crear ---
    def test_crear_sin_incidente(self):
        r = self.nueva("Revisar logs")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Revisar logs", r.text)
        self.assertIn("postit-pendiente", r.text)
        self.assertEqual(self.azure.bugs, [])
        self.assertEqual(self.estado_de(1), Estado.PENDIENTE)

    def test_crear_con_incidente_nuevo_crea_bug_con_el_titulo_de_la_tarea(self):
        r = self.nueva("Falla en SINPE", "777")
        self.assertEqual(self.azure.bugs, ["777 - Falla en SINPE"])
        self.assertIn("Azure 321", r.text)
        self.assertIn("777", r.text)

    def test_crear_con_incidente_existente_no_crea_bug(self):
        self.azure.existentes = {"888": 99}
        r = self.nueva("Algo", "888")
        self.assertEqual(self.azure.bugs, [])
        self.assertIn("Azure 99", r.text)

    def test_titulo_vacio_es_error_y_no_guarda(self):
        r = self.nueva("   ")
        self.assertIn("Escriba el título", r.text)
        self.assertFalse(self.store_path.exists())

    def test_fallo_de_azure_se_muestra_y_no_guarda(self):
        self.azure.falla = True
        r = self.nueva("Algo", "1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Azure caído", r.text)
        self.assertEqual(TaskStore(self.store_path).listar(), [])

    # --- mover / cerrar ---
    def test_mover_entre_columnas(self):
        self.nueva("A")
        r = self.post("/tareas/1/mover", {"estado": "en_proceso"})
        self.assertIn("postit-en_proceso", r.text)
        self.assertNotIn("postit-pendiente", r.text)
        self.post("/tareas/1/mover", {"estado": "entregada"})
        self.assertEqual(self.estado_de(1), Estado.ENTREGADA)
        self.post("/tareas/1/mover", {"estado": "pendiente"})  # también hacia atrás
        self.assertEqual(self.estado_de(1), Estado.PENDIENTE)

    def test_cerrar_oculta_la_tarea_pero_se_conserva(self):
        self.nueva("Cerrame")
        r = self.post("/tareas/1/mover", {"estado": "cerrada"})
        self.assertNotIn("Cerrame", r.text)
        self.assertNotIn("Cerrame", self.client.get("/tareas/").text)
        self.assertEqual(self.estado_de(1), Estado.CERRADA)

    def test_estado_o_id_invalido_no_cambia_nada(self):
        self.nueva("A")
        r = self.post("/tareas/1/mover", {"estado": "volando"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Estado inválido", r.text)
        self.assertEqual(self.estado_de(1), Estado.PENDIENTE)
        r = self.post("/tareas/99/mover", {"estado": "cerrada"})
        self.assertIn("No existe la tarea 99", r.text)
        self.assertEqual(self.post("/tareas/abc/mover", {"estado": "cerrada"}).status_code, 422)

    # --- seguridad ---
    def test_post_sin_token_csrf_se_rechaza(self):
        self.assertEqual(self.client.post("/tareas/nueva", data={"titulo": "x"}).status_code, 403)
        self.assertEqual(self.client.post("/tareas/1/mover", data={"estado": "cerrada"}).status_code, 403)

    def test_el_titulo_se_escapa(self):
        r = self.nueva('<script>alert("x")</script>')
        self.assertNotIn("<script>alert", r.text)
        self.assertIn("&lt;script&gt;", r.text)

    # --- resumen ---
    def test_resumen_cuenta_solo_abiertas(self):
        for t in ("A", "B", "C", "D"):
            self.nueva(t)
        self.post("/tareas/2/mover", {"estado": "en_proceso"})
        self.post("/tareas/3/mover", {"estado": "entregada"})
        self.post("/tareas/4/mover", {"estado": "cerrada"})
        self.assertEqual(tareas_router.service.summary(),
                         ["1 pendiente(s) · 1 en proceso · 1 entregada(s)"])


if __name__ == "__main__":
    unittest.main()
