import unittest
from datetime import date

from timetrack.adapters.azure import build_azure_tasks
from timetrack.adapters.siges import SIGES_TASK_ID, build_siges_days, numident_from_iteration
from timetrack.models import Plan
from timetrack.validate import PlanError, validate_plan

S22 = r"ST_Canales_CX\2026\Sprint 2026.22"
S23 = r"ST_Canales_CX\2026\Sprint 2026.23"


def iteration_for(fecha):
    return S22 if fecha <= date(2026, 10, 30) else S23


def plan_ejemplo():
    return Plan.model_validate({"dias": [
        {"fecha": "2026-10-29", "actividades": [
            {"descripcion": "Soporte a errores en QA", "horas": 4},
            {"descripcion": "Revisión diferencias SINPE Móvil", "horas": 4, "incidente": "100001273"},
        ]},
        {"fecha": "2026-10-30", "actividades": [
            {"descripcion": "Revisión diferencias SINPE Móvil", "horas": 4, "incidente": "100001273"},
            {"descripcion": "Soporte a bugs en QA", "horas": 4},
        ]},
    ]})


class ValidatorTests(unittest.TestCase):
    def test_plan_valido(self):
        validate_plan(plan_ejemplo())

    def test_dia_sin_8_horas_falla(self):
        p = plan_ejemplo()
        p.dias[0].actividades[0].horas = 3
        with self.assertRaises(PlanError) as cm:
            validate_plan(p)
        self.assertIn("29-10-2026", str(cm.exception))

    def test_fecha_repetida_falla(self):
        p = plan_ejemplo()
        p.dias[1].fecha = p.dias[0].fecha
        with self.assertRaises(PlanError):
            validate_plan(p)

    def test_horas_no_positivas_rechazadas_por_modelo(self):
        with self.assertRaises(ValueError):
            Plan.model_validate({"dias": [{"fecha": "2026-10-29",
                "actividades": [{"descripcion": "x", "horas": 0}]}]})


class AzureAdapterTests(unittest.TestCase):
    def test_incidente_agrupado_por_sprint_y_fuera_agrupado(self):
        tareas = build_azure_tasks(plan_ejemplo(), iteration_for)
        con_inc = [t for t in tareas if "incident" in t]
        agrupadas = [t for t in tareas if "parent_title" in t]
        # Dos fechas del mismo incidente y sprint -> UNA sola Task hija, horas sumadas.
        self.assertEqual(len(con_inc), 1)
        self.assertEqual(con_inc[0]["title"], "DEV - Revisión SOA")
        self.assertEqual(con_inc[0]["hours"], 8)
        self.assertEqual(len(con_inc[0]["ref_keys"]), 2)
        self.assertIn("29-10-2026: Revisión diferencias SINPE Móvil", con_inc[0]["description"])
        self.assertIn("30-10-2026: Revisión diferencias SINPE Móvil", con_inc[0]["description"])
        self.assertEqual(len(agrupadas), 1)
        g = agrupadas[0]
        self.assertEqual(g["title"], "DEV - Joseph Ramirez")
        self.assertEqual(g["parent_title"], "DEV - Tareas fuera de incidentes")
        self.assertEqual(g["hours"], 8)
        self.assertIn("29-10-2026: Soporte a errores en QA", g["description"])
        self.assertIn("30-10-2026: Soporte a bugs en QA", g["description"])

    def test_una_tarea_agrupada_por_sprint(self):
        p = Plan.model_validate({"dias": [
            {"fecha": "2026-10-30", "actividades": [{"descripcion": "a", "horas": 8}]},
            {"fecha": "2026-11-02", "actividades": [{"descripcion": "b", "horas": 8}]},
        ]})
        agrupadas = [t for t in build_azure_tasks(p, iteration_for) if "parent_title" in t]
        self.assertEqual({t["iteration"] for t in agrupadas}, {S22, S23})


    def test_mismo_incidente_en_dos_sprints_da_dos_tareas(self):
        p = Plan.model_validate({"dias": [
            {"fecha": "2026-10-30", "actividades": [{"descripcion": "a", "horas": 8, "incidente": "1"}]},
            {"fecha": "2026-11-02", "actividades": [{"descripcion": "b", "horas": 8, "incidente": "1"}]},
        ]})
        con_inc = [t for t in build_azure_tasks(p, iteration_for) if "incident" in t]
        self.assertEqual({t["iteration"] for t in con_inc}, {S22, S23})

    def test_incidentes_distintos_dan_tareas_distintas(self):
        p = Plan.model_validate({"dias": [{"fecha": "2026-10-29", "actividades": [
            {"descripcion": "a", "horas": 4, "incidente": "1"},
            {"descripcion": "b", "horas": 4, "incidente": "2"},
        ]}]})
        con_inc = [t for t in build_azure_tasks(p, iteration_for) if "incident" in t]
        self.assertEqual(sorted(t["incident"] for t in con_inc), ["1", "2"])


class SigesAdapterTests(unittest.TestCase):
    def test_numident(self):
        self.assertEqual(numident_from_iteration(S22), "SPR 22")

    def test_una_linea_por_actividad_con_incidente_en_comentario(self):
        dias = build_siges_days(plan_ejemplo(), iteration_for)
        self.assertEqual(len(dias), 2)
        d29 = dias[0]["tareas"]
        self.assertEqual(len(d29), 2)
        self.assertTrue(all(t["id"] == SIGES_TASK_ID and t["numIdent"] == "SPR 22" for t in d29))
        self.assertEqual(d29[0]["comentario"], "Soporte a errores en QA")
        self.assertTrue(d29[1]["comentario"].startswith("100001273 - "))


if __name__ == "__main__":
    unittest.main()
