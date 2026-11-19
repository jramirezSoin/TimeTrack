import contextlib
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from timetrack.catalog import Catalog
from timetrack.tareas import Estado, TareaError, TaskStore, semana_de
from timetrack import tareas_cli


class FakeGateway:
    def __init__(self, existentes=None, falla=False):
        self.existentes = existentes or {}
        self.falla = falla
        self.busquedas = 0
        self.creados = []

    def find_incident(self, incidente):
        self.busquedas += 1
        if self.falla:
            raise RuntimeError("Azure caído")
        return self.existentes.get(incidente)

    def create_bug(self, titulo, iteration):
        self.creados.append((titulo, iteration))
        return 555


def no_preguntar(_):
    raise AssertionError("no debía pedir título")


class TareasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "tareas.json"
        self.store = TaskStore(self.path)
        self.cat = Catalog(self.dir / "catalog.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_crear_sin_incidente_es_local_y_pendiente(self):
        t = self.store.crear("Revisar logs")
        self.assertEqual((t.id, t.estado, t.azure_id), (1, Estado.PENDIENTE, None))
        self.assertEqual(t.semana, semana_de())
        self.assertEqual(TaskStore(self.path).obtener(1).titulo, "Revisar logs")  # persiste

    def test_incidente_en_catalogo_no_consulta_azure(self):
        self.cat.set_incident("100001273", 42)
        gw = FakeGateway()
        t = self.store.crear("SINPE", incidente="100001273", catalog=self.cat, gateway=gw, ask_title=no_preguntar)
        self.assertEqual(t.azure_id, 42)
        self.assertEqual(gw.busquedas, 0)

    def test_incidente_nuevo_crea_bug_y_queda_en_catalogo(self):
        gw = FakeGateway()
        t = self.store.crear("Falla X", incidente="777", catalog=self.cat, gateway=gw, iteration="Sprint 1")
        self.assertEqual(t.azure_id, 555)
        self.assertEqual(gw.creados, [("777 - Falla X", "Sprint 1")])  # título de la tarea, sin preguntar
        self.assertEqual(Catalog(self.dir / "catalog.json").get_incident("777")["azure_id"], 555)

    def test_incidente_existente_en_azure_no_crea_bug(self):
        gw = FakeGateway(existentes={"888": 99})
        t = self.store.crear("Algo", incidente="888", catalog=self.cat, gateway=gw, ask_title=no_preguntar)
        self.assertEqual((t.azure_id, gw.creados), (99, []))

    def test_fallo_de_azure_no_guarda_la_tarea(self):
        with self.assertRaises(RuntimeError):
            self.store.crear("Algo", incidente="1", catalog=self.cat, gateway=FakeGateway(falla=True),
                             ask_title=no_preguntar)
        self.assertEqual(self.store.listar(), [])
        self.assertFalse(self.path.exists())
        # y el siguiente id no se consumió
        self.assertEqual(self.store.crear("Otra").id, 1)

    def test_incidente_sin_dependencias_es_error(self):
        with self.assertRaises(TareaError):
            self.store.crear("Algo", incidente="1")

    def test_mover_estados_actualiza_fecha(self):
        t = self.store.crear("A")
        t.actualizada  # existe
        for e in Estado:
            self.assertEqual(self.store.mover(1, e).estado, e)
        self.assertEqual(TaskStore(self.path).obtener(1).estado, Estado.CERRADA)  # reabrir permitido
        self.assertEqual(self.store.mover(1, Estado.PENDIENTE).estado, Estado.PENDIENTE)

    def test_listar_filtra_por_semana_y_estado_y_resumen(self):
        self.store.crear("A", semana="2026-W45")
        self.store.crear("B", semana="2026-W45")
        self.store.crear("C", semana="2026-W46")
        self.store.mover(2, Estado.EN_PROCESO)
        self.assertEqual([t.titulo for t in self.store.listar(semana="2026-W45")], ["A", "B"])
        self.assertEqual([t.titulo for t in self.store.listar(semana="2026-W45", estado=Estado.EN_PROCESO)], ["B"])
        r = self.store.resumen("2026-W45")
        self.assertEqual((r[Estado.PENDIENTE], r[Estado.EN_PROCESO], r[Estado.CERRADA]), (1, 1, 0))
        self.assertEqual(sum(self.store.resumen().values()), 3)

    def test_ids_no_se_reutilizan_tras_eliminar(self):
        self.store.crear("A")
        self.store.crear("B")
        self.store.eliminar(2)
        self.assertEqual(TaskStore(self.path).crear("C").id, 3)

    def test_editar_y_validaciones(self):
        self.store.crear("A")
        t = self.store.editar(1, titulo="  Nuevo ", semana="2026-w50", notas="n")
        self.assertEqual((t.titulo, t.semana, t.notas), ("Nuevo", "2026-W50", "n"))
        with self.assertRaises(ValueError):
            self.store.editar(1, semana="2026-45")
        with self.assertRaises(ValueError):
            self.store.editar(1, titulo="   ")
        with self.assertRaises(ValueError):
            self.store.crear("   ")
        with self.assertRaises(TareaError):
            self.store.mover(99, Estado.CERRADA)

    def test_json_corrupto_falla_y_no_se_toca(self):
        self.path.write_text("{ no es json", encoding="utf-8")
        with self.assertRaises(TareaError):
            TaskStore(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ no es json")

    def test_semana_iso(self):
        self.assertEqual(semana_de(date(2026, 11, 6)), "2026-W45")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name) / "tareas.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tareas_cli.main(list(argv), store=self.store)
        return code, out.getvalue(), err.getvalue()

    def test_flujo_basico(self):
        self.assertEqual(self.run_cli("nueva", "Hacer X")[0], 0)
        self.assertEqual(self.run_cli("mover", "1", "en_proceso")[0], 0)
        code, out, _ = self.run_cli("listar")
        self.assertIn("En proceso (1)", out)
        self.assertIn("#1 Hacer X", out)
        code, out, _ = self.run_cli("resumen")
        self.assertIn("En proceso", out)
        self.assertEqual(self.run_cli("eliminar", "1")[0], 0)

    def test_errores_devuelven_2_sin_traza(self):
        code, _, err = self.run_cli("mover", "9", "cerrada")
        self.assertEqual(code, 2)
        self.assertIn("No existe la tarea 9", err)
        self.assertEqual(self.run_cli("nueva", "X", "--semana", "mala")[0], 2)
        self.assertEqual(self.run_cli("editar", "1")[0], 2)


if __name__ == "__main__":
    unittest.main()
