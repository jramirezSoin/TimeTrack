import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from timetrack.catalog import Catalog
from timetrack.ledger import Ledger, pending_activities
from timetrack.models import Plan
from timetrack.pipeline import run
from timetrack.validate import PlanError

PLAN_JSON = Path(__file__).with_name("plan_ejemplo.json")
S22 = r"ST_Canales_CX\2026\Sprint 2026.22"


class FakeAzure:
    def __init__(self, existentes=None, falla_task=False):
        self.existentes = {"100001273": 988523} if existentes is None else existentes
        self.falla_task = falla_task
        self.tasks, self.grouped, self.bugs = [], [], []

    def iteration_for(self, fecha):
        return S22

    def find_incident(self, inc):
        return self.existentes.get(inc)

    def create_bug(self, titulo, iteration):
        self.bugs.append(titulo)
        return 1

    def upsert_child(self, parent_id, task):
        if self.falla_task:
            raise RuntimeError("boom")
        self.tasks.append({**task, "parent_id": parent_id})
        return 900 + len(self.tasks), "creada"

    def upsert_grouped(self, task):
        self.grouped.append(task)
        return 995051


class FakeSiges:
    def __init__(self):
        self.enviados = []

    def send_day(self, fecha, tareas, cerrar_dia=False):
        self.enviados.append((fecha, tareas, cerrar_dia))
        return 200, "ok"


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.catalog = Catalog(d / "catalog.json")
        self.ledger_path = d / "ledger.json"
        self.plan = Plan.model_validate(json.loads(PLAN_JSON.read_text(encoding="utf-8")))
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, azure, siges, **kw):
        return run(
            self.plan, catalog=self.catalog, ledger=Ledger(self.ledger_path),
            azure=azure, siges=siges, out=self.logs.append,
            confirm=lambda _m: True, ask_title=lambda _i: "x", **kw,
        )

    def test_dry_run_no_envia_ni_registra(self):
        az, sg = FakeAzure(), FakeSiges()
        self.assertEqual(self.go(az, sg), 0)
        self.assertEqual((az.tasks, az.grouped, sg.enviados), ([], [], []))
        self.assertFalse(self.ledger_path.exists())

    def test_apply_envia_todo(self):
        az, sg = FakeAzure(), FakeSiges()
        self.assertEqual(self.go(az, sg, apply=True), 0)
        self.assertEqual(len(az.tasks), 1)          # 1 hija del incidente (2 fechas, 8 h)
        self.assertEqual(az.tasks[0]["parent_id"], 988523)
        self.assertEqual(az.tasks[0]["title"], "DEV - Revisión SOA")
        self.assertEqual(az.tasks[0]["hours"], 8)
        self.assertEqual(len(az.grouped), 1)        # 1 agrupada
        self.assertEqual(az.grouped[0]["hours"], 8)
        self.assertEqual([e[0] for e in sg.enviados], ["2026-10-29", "2026-10-30"])

    def test_ledger_guarda_la_fecha_de_la_tarea_en_azure_y_siges(self):
        self.go(FakeAzure(), FakeSiges(), apply=True)
        entradas = Ledger(self.ledger_path).entries().values()
        azure = [e for e in entradas if e["sistema"] == "azure"]
        siges = [e for e in entradas if e["sistema"] == "siges"]
        self.assertTrue(azure and all(e.get("fecha") for e in azure))
        # La Task del incidente agrupa dos días: cada actividad conserva el suyo.
        self.assertEqual({"2026-10-29", "2026-10-30"} <= {e["fecha"] for e in azure}, True)
        self.assertEqual(sorted(e["fecha"] for e in siges), ["2026-10-29", "2026-10-30"])

    def test_reintento_no_duplica(self):
        az, sg = FakeAzure(), FakeSiges()
        self.go(az, sg, apply=True)
        az2, sg2 = FakeAzure(), FakeSiges()
        self.assertEqual(self.go(az2, sg2, apply=True), 0)
        self.assertEqual((az2.tasks, az2.grouped, sg2.enviados), ([], [], []))

    def test_fallo_parcial_solo_reintenta_lo_pendiente(self):
        az, sg = FakeAzure(falla_task=True), FakeSiges()
        self.assertEqual(self.go(az, sg, apply=True), 1)   # incidentes fallaron
        self.assertEqual(len(az.grouped), 1)               # la agrupada sí se envió
        az2, sg2 = FakeAzure(), FakeSiges()
        self.assertEqual(self.go(az2, sg2, apply=True), 0)
        self.assertEqual(len(az2.tasks), 1)                # reintenta la del incidente
        self.assertEqual(az2.grouped, [])                  # la agrupada no se repite
        self.assertEqual(sg2.enviados, [])                 # SIGES ya estaba

    def test_cancelar_no_envia(self):
        az, sg = FakeAzure(), FakeSiges()
        r = run(self.plan, catalog=self.catalog, ledger=Ledger(self.ledger_path),
                azure=az, siges=sg, apply=True, confirm=lambda _m: False, out=self.logs.append)
        self.assertEqual(r, 1)
        self.assertEqual((az.tasks, az.grouped, sg.enviados), ([], [], []))

    def test_dia_sin_8_horas_aborta_antes_de_todo(self):
        self.plan.dias[0].actividades[0].horas = 1
        az, sg = FakeAzure(), FakeSiges()
        with self.assertRaises(PlanError):
            self.go(az, sg, apply=True)
        self.assertEqual((az.tasks, az.grouped, sg.enviados), ([], [], []))

    def test_incidente_inexistente_crea_bug_al_enviar(self):
        az, sg = FakeAzure(existentes={}), FakeSiges()
        self.go(az, sg, apply=True)
        self.assertEqual(az.bugs, ["100001273 - x"])
        self.assertEqual(az.tasks[0]["parent_id"], 1)


class PreviewExecuteTests(unittest.TestCase):
    """build_preview / execute: las piezas que reutiliza el dashboard web."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.catalog = Catalog(d / "catalog.json")
        self.ledger_path = d / "ledger.json"
        self.plan = Plan.model_validate(json.loads(PLAN_JSON.read_text(encoding="utf-8")))

    def tearDown(self):
        self.tmp.cleanup()

    def preview(self, azure):
        from timetrack.pipeline import build_preview
        return build_preview(self.plan, catalog=self.catalog,
                             ledger=Ledger(self.ledger_path), azure=azure)

    def execute(self, preview, azure, siges, ask_title=lambda _i: "x"):
        from timetrack.pipeline import execute
        return execute(preview, catalog=self.catalog, ledger=Ledger(self.ledger_path),
                       azure=azure, siges=siges, ask_title=ask_title, out=lambda _m: None)

    def test_build_preview_no_escribe_nada(self):
        az, sg = FakeAzure(), FakeSiges()
        pv = self.preview(az)
        self.assertTrue(pv.pending)
        self.assertEqual(pv.incidents["100001273"].state, "azure")
        self.assertEqual(pv.new_incidents, [])
        self.assertEqual((az.tasks, az.grouped, az.bugs, sg.enviados), ([], [], [], []))
        self.assertFalse(self.ledger_path.exists())
        self.assertIsNone(self.catalog.get_incident("100001273"))

    def test_build_preview_marca_incidentes_nuevos(self):
        pv = self.preview(FakeAzure(existentes={}))
        self.assertEqual(pv.new_incidents, ["100001273"])

    def test_build_preview_valida_las_8_horas(self):
        self.plan.dias[0].actividades[0].horas = 1
        with self.assertRaises(PlanError):
            self.preview(FakeAzure())

    def test_execute_devuelve_resultado(self):
        az, sg = FakeAzure(), FakeSiges()
        res = self.execute(self.preview(az), az, sg)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.azure), 2)          # hija del incidente + agrupada
        self.assertEqual([s["fecha"] for s in res.siges], ["2026-10-29", "2026-10-30"])

    def test_execute_crea_bug_con_titulo_recibido(self):
        az, sg = FakeAzure(existentes={}), FakeSiges()
        titulos = {"100001273": "Falla SINPE"}
        res = self.execute(self.preview(az), az, sg, ask_title=lambda i: titulos[i])
        self.assertTrue(res.ok)
        self.assertEqual(az.bugs, ["100001273 - Falla SINPE"])

    def test_execute_reporta_errores_sin_abortar(self):
        az, sg = FakeAzure(falla_task=True), FakeSiges()
        res = self.execute(self.preview(az), az, sg)
        self.assertFalse(res.ok)
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(len(res.azure), 1)          # la agrupada sí salió
        self.assertEqual(len(res.siges), 2)          # SIGES no se afecta


class ReadOnlyViewsTests(unittest.TestCase):
    def test_entries_e_incidents_son_copias(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d) / "l.json")
            led.add("k", sistema="azure")
            copia = led.entries()
            copia["k"]["sistema"] = "otro"
            self.assertEqual(led.entries()["k"]["sistema"], "azure")
            cat = Catalog(Path(d) / "c.json")
            cat.set_incident("1", 10, "t")
            self.assertEqual(cat.incidents()["1"]["azure_id"], 10)
            cat.incidents()["1"]["azure_id"] = 99
            self.assertEqual(cat.get_incident("1")["azure_id"], 10)


class LedgerTests(unittest.TestCase):
    def test_ledger_vacio_o_corrupto_falla_con_mensaje_claro(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.json"
            p.write_text("", encoding="utf-8")
            with self.assertRaises(RuntimeError) as cm:
                Ledger(p)
            self.assertIn("corrupto", str(cm.exception))
            self.assertEqual(p.read_text(encoding="utf-8"), "")  # no lo toca

    def test_escritura_atomica_no_deja_temporales(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.json"
            Ledger(p).add("k", sistema="azure")
            self.assertEqual([f.name for f in Path(d).iterdir()], ["l.json"])

    def test_pending_filtra_lo_ya_enviado(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d) / "l.json")
            plan = Plan.model_validate(json.loads(PLAN_JSON.read_text(encoding="utf-8")))
            from timetrack.ledger import activity_key
            primera = plan.dias[0].actividades[0]
            led.add(activity_key("azure", date(2026, 10, 29), primera))
            pend = pending_activities(plan, "azure", Ledger(Path(d) / "l.json"))
            self.assertEqual(len(pend.dias[0].actividades), 1)
            self.assertEqual(len(pend.dias), 2)


if __name__ == "__main__":
    unittest.main()
