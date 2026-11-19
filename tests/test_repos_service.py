"""azure_repos_service con fork: cuerpo del PR (forkSource) y comparación contra la punta del destino.
Se sustituye azure_devops_service por un falso: sin red ni azure/config.json."""
import importlib
import sys
import types
import unittest
from pathlib import Path

_AZURE = str(Path(__file__).resolve().parent.parent / "azure")
FORK_ID = "87abfcb2-cd03-4314-8433-e37eb99c1242"
REVIEWER_ID = "829adacc-798c-4020-ae9f-bdcf6909a26f"
SHA = "a" * 40


def _fake_ado(calls, responder):
    m = types.ModuleType("azure_devops_service")
    m.config = {"repos": {"default": "999dc9bd", "target_branch": "qa", "fork": "mi-fork",
                          "fork_project": "Otro", "source_branch": "dev"}}
    m.ORG, m.PROJECT = "org", "TP_SOA"

    def ado_fetch(url, method="GET", body=None, headers=None):
        calls.append((method, url, body))
        return responder(method, url, body)
    m.ado_fetch = ado_fetch
    return m


class ForkTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._saved = {k: sys.modules.get(k) for k in ("azure_devops_service", "azure_repos_service")}
        sys.path.insert(0, _AZURE)

    def tearDown(self):
        sys.path.remove(_AZURE)
        for k, v in self._saved.items():
            sys.modules.pop(k, None)
            if v is not None:
                sys.modules[k] = v

    def svc(self, responder):
        sys.modules["azure_devops_service"] = _fake_ado(self.calls, responder)
        sys.modules.pop("azure_repos_service", None)
        return importlib.import_module("azure_repos_service")

    def test_crear_pr_envia_forksource_y_repo_principal(self):
        def r(method, url, body):
            if method == "GET" and "/pullrequests?" in url:
                return {"value": []}
            if method == "GET":  # resolver id del fork
                return {"id": FORK_ID}
            return {"pullRequestId": 42}
        svc = self.svc(r)
        res = svc.create_pull_request("dev", "T", description="D")
        self.assertEqual(res, {"id": 42, "url": "https://dev.azure.com/org/TP_SOA/_git/999dc9bd/pullrequest/42",
                               "creado": True})
        method, url, body = self.calls[-1]
        self.assertIn("/TP_SOA/_apis/git/repositories/999dc9bd/pullrequests", url)
        self.assertEqual(body["sourceRefName"], "refs/heads/dev")
        self.assertEqual(body["targetRefName"], "refs/heads/qa")
        self.assertEqual(body["forkSource"], {"name": "refs/heads/dev", "repository": {"id": FORK_ID}})
        self.assertTrue(any(f"sourceRepositoryId={FORK_ID}" in c[1] for c in self.calls))

    def test_crear_pr_agrega_reviewers_de_config(self):
        def r(method, url, body):
            if method == "GET" and "/pullrequests?" in url:
                return {"value": []}
            if method == "GET":
                return {"id": FORK_ID}
            return {"pullRequestId": 1}
        svc = self.svc(r)
        svc._repos_cfg["reviewers"] = [REVIEWER_ID]
        svc.create_pull_request("dev", "T")
        self.assertEqual(self.calls[-1][2]["reviewers"], [{"id": REVIEWER_ID}])
        self.assertFalse(any("identities" in c[1] for c in self.calls))  # GUID: sin consulta

    def _identidades(self, value):
        def r(method, url, body):
            if "identities" in url:
                return {"value": value}
            return {"id": FORK_ID}
        return self.svc(r)

    def test_reviewer_por_correo_se_resuelve_a_guid_y_se_cachea(self):
        svc = self._identidades([{"id": REVIEWER_ID, "providerDisplayName": "Ana Perez"}])
        self.assertEqual(svc._reviewer_id("ana@x.com"), REVIEWER_ID)
        self.assertEqual(svc._reviewer_id("ANA@x.com"), REVIEWER_ID)
        consultas = [c for c in self.calls if "identities" in c[1]]
        self.assertEqual(len(consultas), 1)
        self.assertIn("https://vssps.dev.azure.com/org/_apis/identities", consultas[0][1])
        self.assertIn("filterValue=ana%40x.com", consultas[0][1])

    def test_reviewer_con_varias_coincidencias_elige_la_exacta(self):
        svc = self._identidades([
            {"id": "otro", "providerDisplayName": "Ana Perez Mora"},
            {"id": REVIEWER_ID, "providerDisplayName": "Ana Perez"},
        ])
        self.assertEqual(svc._reviewer_id("Ana Perez"), REVIEWER_ID)

    def test_reviewer_ambiguo_o_inexistente_falla(self):
        svc = self._identidades([{"id": "a", "providerDisplayName": "Ana Uno"},
                                 {"id": "b", "providerDisplayName": "Ana Dos"}])
        with self.assertRaisesRegex(RuntimeError, "2 coincidencias"):
            svc._reviewer_id("Ana")
        svc = self._identidades([])
        with self.assertRaisesRegex(RuntimeError, "no se encontró"):
            svc._reviewer_id("nadie@x.com")

    def test_mis_prs_activos_filtra_por_creador(self):
        def r(method, url, body):
            if "connectionData" in url:
                return {"authenticatedUser": {"id": "yo-guid"}}
            return {"value": [
                {"pullRequestId": 1, "title": "A", "sourceRefName": "refs/heads/dev",
                 "targetRefName": "refs/heads/qa", "creationDate": "2026-01-01T00:00:00Z",
                 "reviewers": [{"displayName": "Ana", "vote": 10}]},
                {"pullRequestId": 2, "title": "B", "sourceRefName": "refs/heads/dev",
                 "targetRefName": "refs/heads/qa", "creationDate": "2026-02-01T00:00:00Z", "isDraft": True,
                 "repository": {"name": "TP_SOA", "project": {"name": "TP_SOA"}}},
            ]}
        prs = self.svc(r).list_my_active_prs()
        self.assertIn("searchCriteria.creatorId=yo-guid", self.calls[-1][1])
        self.assertEqual([p["id"] for p in prs], [2, 1])
        self.assertTrue(prs[0]["draft"])
        self.assertEqual(prs[0]["url"], "https://org.visualstudio.com/TP_SOA/_git/TP_SOA/pullrequest/2")
        self.assertEqual(prs[1]["reviewers"], [{"nombre": "Ana", "voto": 10}])

    def test_pr_activo_se_reutiliza_sin_post(self):
        def r(method, url, body):
            if "/pullrequests?" in url:
                return {"value": [{"pullRequestId": 9}]}
            return {"id": FORK_ID}
        res = self.svc(r).create_pull_request("dev", "T")
        self.assertFalse(res["creado"])
        self.assertFalse(any(c[0] == "POST" for c in self.calls))

    def test_comparacion_contra_la_punta_del_destino(self):
        def r(method, url, body):
            if "/refs?" in url:
                return {"value": [{"name": "refs/heads/qa", "objectId": SHA}]}
            # commitsbatch recorre desde compareVersion: para "ahead" la branch va ahí
            if body["compareVersion"]["versionType"] == "branch":  # ahead
                return {"value": [{"commitId": "b" * 40, "comment": "cambio\ndetalle", "author": {"name": "yo"}}]}
            return {"value": []}
        st = self.svc(r).commits_status("dev")
        self.assertEqual((st["ahead_count"], st["behind_count"]), (1, 0))
        self.assertEqual(st["ahead"][0]["mensaje"], "cambio")
        post = [c for c in self.calls if c[0] == "POST"][0]
        self.assertIn("/Otro/_apis/git/repositories/mi-fork/commitsbatch", post[1])
        self.assertEqual(post[2]["itemVersion"], {"version": SHA, "versionType": "commit"})

    def test_fallo_de_comparacion_devuelve_aviso(self):
        def r(method, url, body):
            if "/refs?" in url:
                return {"value": [{"name": "refs/heads/qa", "objectId": SHA}]}
            raise RuntimeError("404 Not Found")
        st = self.svc(r).commits_status("dev")
        self.assertIn("404 Not Found", st["aviso"])
        self.assertEqual(st["ahead_count"], 0)

    def test_branches_salen_del_fork(self):
        svc = self.svc(lambda m, u, b: {"value": [{"name": "refs/heads/dev"}]})
        self.assertEqual(svc.list_branches(), ["dev"])
        self.assertIn("/Otro/_apis/git/repositories/mi-fork/refs", self.calls[0][1])


if __name__ == "__main__":
    unittest.main()
