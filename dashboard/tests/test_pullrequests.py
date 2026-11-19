"""Pruebas del módulo de Pull Requests (TestClient y repos falso; sin red)."""
import unittest

from fastapi.testclient import TestClient

from dashboard.app.main import create_app
from dashboard.app.modules import pullrequests
from dashboard.app.modules.pullrequests import router as pr_router
from dashboard.app.modules.pullrequests.service import PullRequestsService


class FakeRepos:
    def __init__(self, ahead=2, behind=1, active=None, falla=False, aviso=None):
        self.ahead, self.behind, self.active, self.falla = ahead, behind, active, falla
        self.aviso = aviso
        self.created = []

    def default_target(self):
        return "main"

    def default_source(self):
        return "dev"

    def branches(self):
        if self.falla:
            raise RuntimeError("Azure caído")
        return ["feat/a", "main"]

    def status(self, source, target=None, repo=None):
        if self.falla:
            raise RuntimeError("Azure caído")
        mk = lambda n: [{"short": f"abc{i}", "autor": "yo", "mensaje": f"commit-{i}"} for i in range(n)]
        st = {"source": source, "target": target or "main", "ahead_count": self.ahead,
              "behind_count": self.behind, "ahead": mk(self.ahead), "behind": mk(self.behind)}
        if self.aviso:
            st["aviso"] = self.aviso
        return st

    def active_pr(self, source, target=None, repo=None):
        return self.active

    def create_pr(self, source, title, target=None, description="", repo=None, draft=False):
        self.created.append((source, title, target, draft))
        return {"id": 7, "url": "http://x/pr/7", "creado": True}


class PullRequestsDashboardTests(unittest.TestCase):
    def setUp(self):
        self.repos = FakeRepos()
        self._orig = pr_router.service
        pr_router.service = PullRequestsService(repos_factory=lambda: self.repos)
        self.app = create_app(modules=[pullrequests.module])
        self.client = TestClient(self.app, base_url="http://localhost")
        self.token = self.app.state.csrf_token

    def tearDown(self):
        pr_router.service = self._orig

    def post(self, url, data):
        return self.client.post(url, data=data, headers={"X-CSRF-Token": self.token})

    def test_portada_y_menu(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('href="/pullrequests/"', r.text)

    def test_pagina_lista_branches(self):
        r = self.client.get("/pullrequests/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<option value="feat/a">', r.text)
        self.assertIn('value="main"', r.text)

    def test_pagina_abre_aunque_azure_falle(self):
        self.repos.falla = True
        r = self.client.get("/pullrequests/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Azure caído", r.text)

    def test_estado_muestra_commits_y_formulario(self):
        r = self.post("/pullrequests/estado", {"branch": "feat/a", "destino": ""})
        self.assertIn("feat/a → main", r.text)
        self.assertIn("commit-1", r.text)
        self.assertIn("/pullrequests/crear", r.text)

    def test_estado_sin_commits_no_ofrece_crear(self):
        self.repos.ahead = 0
        r = self.post("/pullrequests/estado", {"branch": "feat/a"})
        self.assertNotIn("/pullrequests/crear", r.text)
        self.assertIn("No hay commits nuevos", r.text)

    def test_aviso_de_comparacion_no_bloquea_crear(self):
        self.repos.ahead = self.repos.behind = 0
        self.repos.aviso = "No se pudo comparar"
        r = self.post("/pullrequests/estado", {"branch": "dev"})
        self.assertIn("No se pudo comparar", r.text)
        self.assertIn("/pullrequests/crear", r.text)

    def test_origen_por_defecto_en_la_pagina(self):
        self.assertIn('value="dev"', self.client.get("/pullrequests/").text)

    def test_estado_avisa_pr_activo(self):
        self.repos.active = {"pullRequestId": 5}
        r = self.post("/pullrequests/estado", {"branch": "feat/a"})
        self.assertIn("#5", r.text)

    def test_estado_error_de_azure(self):
        self.repos.falla = True
        r = self.post("/pullrequests/estado", {"branch": "feat/a"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Azure caído", r.text)

    def test_crear_pr(self):
        r = self.post("/pullrequests/crear", {"branch": "feat/a", "destino": "main", "titulo": "Mi PR", "draft": "1"})
        self.assertIn("http://x/pr/7", r.text)
        self.assertEqual(self.repos.created, [("feat/a", "Mi PR", "main", True)])

    def test_crear_sin_titulo_es_error(self):
        r = self.post("/pullrequests/crear", {"branch": "feat/a", "titulo": "  "})
        self.assertIn("Indique la branch y el título", r.text)
        self.assertEqual(self.repos.created, [])

    def test_post_sin_csrf_se_rechaza(self):
        r = self.client.post("/pullrequests/crear", data={"branch": "x", "titulo": "y"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
