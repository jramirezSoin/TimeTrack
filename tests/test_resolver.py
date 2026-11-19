import tempfile
import unittest
from pathlib import Path

from timetrack.catalog import Catalog
from timetrack.resolver import resolve_incident


class FakeGateway:
    def __init__(self, existentes=None):
        self.existentes = existentes or {}
        self.busquedas = 0
        self.creados = []

    def find_incident(self, incidente):
        self.busquedas += 1
        return self.existentes.get(incidente)

    def create_bug(self, titulo, iteration):
        self.creados.append((titulo, iteration))
        return 555


def no_preguntar(_):
    raise AssertionError("no debía pedir título")


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "catalog.json"
        self.cat = Catalog(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalogo_evita_buscar_en_azure(self):
        self.cat.set_incident("100001273", 42)
        gw = FakeGateway()
        self.assertEqual(resolve_incident("100001273", self.cat, gw, no_preguntar), 42)
        self.assertEqual(gw.busquedas, 0)

    def test_encontrado_en_azure_se_guarda_en_catalogo(self):
        gw = FakeGateway({"100001273": 77})
        self.assertEqual(resolve_incident("100001273", self.cat, gw, no_preguntar), 77)
        self.assertEqual(Catalog(self.path).get_incident("100001273")["azure_id"], 77)

    def test_inexistente_pide_titulo_y_crea_bug(self):
        gw = FakeGateway()
        r = resolve_incident("100009999", self.cat, gw, lambda _: "Falla en SINPE", "ITER")
        self.assertEqual(r, 555)
        self.assertEqual(gw.creados, [("100009999 - Falla en SINPE", "ITER")])
        self.assertEqual(Catalog(self.path).get_incident("100009999")["azure_id"], 555)

    def test_titulo_que_ya_incluye_numero_no_se_duplica(self):
        gw = FakeGateway()
        resolve_incident("100009999", self.cat, gw, lambda _: "100009999 Falla")
        self.assertEqual(gw.creados[0][0], "100009999 Falla")

    def test_titulo_vacio_falla_sin_crear(self):
        gw = FakeGateway()
        with self.assertRaises(ValueError):
            resolve_incident("100009999", self.cat, gw, lambda _: "  ")
        self.assertEqual(gw.creados, [])


if __name__ == "__main__":
    unittest.main()
