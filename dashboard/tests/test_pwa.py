"""Pruebas del PWA: manifiesto, íconos, service worker, pantalla sin servidor y que la seguridad siga intacta."""
import io
import json
import re
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from dashboard.app.main import create_app
from dashboard.app.modules import horas, tareas, utilidades


class PwaTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(modules=[horas.module, tareas.module, utilidades.module])
        self.client = TestClient(self.app, base_url="http://localhost")
        self.manifest = self.client.get("/manifest.webmanifest").json()

    # --- manifiesto ---
    def test_manifiesto_tipo_y_cache(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/manifest+json"))
        self.assertEqual(r.headers["cache-control"], "no-cache")

    def test_manifiesto_cumple_lo_necesario_para_instalar(self):
        m = self.manifest
        for campo in ("name", "short_name", "start_url", "scope", "display", "icons"):
            self.assertTrue(m.get(campo), campo)
        self.assertEqual(m["display"], "standalone")
        self.assertEqual((m["start_url"], m["scope"]), ("/", "/"))
        tamanos = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
        self.assertIn(("192x192", "any"), tamanos)
        self.assertIn(("512x512", "any"), tamanos)
        self.assertIn(("512x512", "maskable"), tamanos)

    def test_cada_icono_existe_y_tiene_las_dimensiones_declaradas(self):
        for icono in self.manifest["icons"]:
            r = self.client.get(icono["src"])
            self.assertEqual(r.status_code, 200, icono["src"])
            if icono["type"] == "image/png":
                w, h = icono["sizes"].split("x")
                self.assertEqual(Image.open(io.BytesIO(r.content)).size, (int(w), int(h)), icono["src"])
        self.assertEqual(self.client.get("/static/pwa/apple-touch-icon.png").status_code, 200)

    def test_los_atajos_apuntan_a_paginas_que_existen(self):
        urls = [s["url"] for s in self.manifest["shortcuts"]]
        self.assertTrue(urls)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)  # sigue redirecciones (/utilidades/)

    # --- service worker ---
    def test_service_worker_se_sirve_desde_la_raiz_sin_cache(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["content-type"])
        self.assertEqual(r.headers["cache-control"], "no-cache")

    def test_toda_la_precarga_existe(self):
        """Si una sola URL de la lista falla, cache.addAll rechaza y el service worker no se instala."""
        sw = self.client.get("/sw.js").text
        lista = re.search(r"const PRECACHE = \[(.*?)\];", sw, re.DOTALL).group(1)
        urls = re.findall(r'"(/[^"]*)"', lista)
        self.assertGreater(len(urls), 5)
        self.assertIn("/offline", urls)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_reglas_del_service_worker_para_no_romper_el_csrf(self):
        sw = self.client.get("/sw.js").text
        self.assertIn('req.method !== "GET"', sw)                      # los POST no se interceptan
        self.assertIn('req.mode === "navigate"', sw)                   # HTML: solo red + /offline
        self.assertRegex(sw, r'navigate"\)\s*\{[^}]*fetch\(req\)\.catch')
        # Ninguna ruta de HTML ni fragmento HTMX está en la precarga ni se guarda en caché.
        lista = re.search(r"const PRECACHE = \[(.*?)\];", sw, re.DOTALL).group(1)
        for ruta in ('"/"', '"/horas', '"/tareas', '"/utilidades'):
            self.assertNotIn(ruta, lista)
        self.assertNotIn("cache.put(req", sw.split("self.addEventListener(\"fetch\"")[1].split("primeroCache(req)")[0])

    # --- sin servidor ---
    def test_pantalla_sin_servidor(self):
        r = self.client.get("/offline")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Servidor no disponible", r.text)
        self.assertIn("uvicorn dashboard.app.main:app", r.text)
        self.assertNotIn("http://", r.text.replace("http://127.0.0.1", ""))  # autocontenida: nada externo

    # --- plantilla base ---
    def test_todas_las_paginas_enlazan_el_manifiesto_y_registran_el_sw(self):
        for url in ("/", "/horas/", "/tareas/", "/utilidades/json"):
            html = self.client.get(url).text
            self.assertIn('<link rel="manifest" href="/manifest.webmanifest">', html, url)
            self.assertIn('name="theme-color"', html, url)
            self.assertIn('rel="apple-touch-icon"', html, url)
            self.assertIn('serviceWorker.register("/sw.js")', html, url)
            self.assertIn("htmx:sendError", html, url)

    # --- la seguridad no cambia ---
    def test_host_ajeno_sigue_rechazado_tambien_en_el_pwa(self):
        for url in ("/manifest.webmanifest", "/sw.js", "/offline"):
            r = self.client.get(url, headers={"Host": "evil.example"})
            self.assertEqual(r.status_code, 400, url)

    def test_los_post_siguen_exigiendo_csrf(self):
        self.assertEqual(self.client.post("/tareas/nueva", data={"titulo": "x"}).status_code, 403)
        self.assertEqual(self.client.post("/sw.js").status_code, 403)

    def test_no_se_expone_documentacion(self):
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)


if __name__ == "__main__":
    unittest.main()
