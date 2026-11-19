import contextlib
import io
import unittest

from timetrack import pr_cli


class FakeRepos:
    def __init__(self, ahead=2, behind=1, active=None):
        self.ahead, self.behind, self.active = ahead, behind, active
        self.created = []

    def status(self, source, target=None, repo=None):
        mk = lambda n: [{"short": f"abc{i}", "autor": "yo", "mensaje": f"c{i}"} for i in range(n)]
        return {"source": source, "target": target or "main", "ahead_count": self.ahead,
                "behind_count": self.behind, "ahead": mk(self.ahead), "behind": mk(self.behind)}

    def active_pr(self, source, target=None, repo=None):
        return self.active

    def create_pr(self, source, title, target=None, description="", repo=None, draft=False):
        self.created.append((source, title, draft))
        return {"id": 7, "url": "http://x/7", "creado": True}


def run(argv, fake):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pr_cli.main(argv, azure=fake)
    return code, out.getvalue(), err.getvalue()


class PrCliTest(unittest.TestCase):
    def test_estado_muestra_ahead_y_behind(self):
        code, out, _ = run(["estado", "--branch", "feat"], FakeRepos())
        self.assertEqual(code, 0)
        self.assertIn("feat -> main", out)
        self.assertIn("Pendientes de integrar (irían en el PR) (2)", out)
        self.assertIn("Le faltan a tu branch (están en destino) (1)", out)

    def test_crear_sin_apply_no_crea(self):
        fake = FakeRepos()
        code, out, _ = run(["crear", "--branch", "feat", "--titulo", "T"], fake)
        self.assertEqual(code, 0)
        self.assertIn("[dry-run]", out)
        self.assertEqual(fake.created, [])

    def test_crear_con_apply(self):
        fake = FakeRepos()
        code, out, _ = run(["crear", "--branch", "feat", "--titulo", "T", "--draft", "--apply"], fake)
        self.assertEqual(code, 0)
        self.assertEqual(fake.created, [("feat", "T", True)])
        self.assertIn("http://x/7", out)

    def test_crear_sin_commits_nuevos(self):
        fake = FakeRepos(ahead=0)
        code, _, err = run(["crear", "--branch", "feat", "--titulo", "T", "--apply"], fake)
        self.assertEqual(code, 2)
        self.assertEqual(fake.created, [])

    def test_avisa_pr_activo_existente(self):
        fake = FakeRepos(active={"pullRequestId": 5})
        _, out, _ = run(["crear", "--branch", "feat", "--titulo", "T"], fake)
        self.assertIn("Ya existe un PR activo: #5", out)


if __name__ == "__main__":
    unittest.main()
