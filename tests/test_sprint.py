import unittest
from datetime import date

from timetrack.sprint import agrupar_por_padre, elegir_iteracion, html_a_texto, parse_sprint, totales

ITERS = [
    {"name": "Sprint 2025.22", "path": r"P\2025\Sprint 2025.22"},
    {"name": "Sprint 2026.21", "path": r"P\2026\Sprint 2026.21"},
    {"name": "Sprint 2026.22", "path": r"P\2026\Sprint 2026.22"},
    {"name": "Backlog sin número", "path": "P"},
]


class ParseTests(unittest.TestCase):
    def test_formatos_validos(self):
        self.assertEqual(parse_sprint("22"), (None, 22))
        self.assertEqual(parse_sprint(" Sprint 22 "), (None, 22))
        self.assertEqual(parse_sprint("2026.22"), (2026, 22))
        self.assertEqual(parse_sprint("sprint 2025.5"), (2025, 5))

    def test_formatos_invalidos(self):
        for malo in ("", "abc", "22'; DROP", "2026.", "1234567"):
            with self.assertRaises(ValueError, msg=malo):
                parse_sprint(malo)


class ElegirTests(unittest.TestCase):
    def test_sin_anio_prefiere_el_actual(self):
        self.assertEqual(elegir_iteracion(ITERS, None, 22, date(2026, 11, 6))["path"], r"P\2026\Sprint 2026.22")

    def test_sin_anio_cae_al_mas_reciente_si_el_actual_no_lo_tiene(self):
        self.assertEqual(elegir_iteracion(ITERS, None, 22, date(2027, 1, 5))["path"], r"P\2026\Sprint 2026.22")

    def test_con_anio_exacto(self):
        self.assertEqual(elegir_iteracion(ITERS, 2025, 22)["path"], r"P\2025\Sprint 2025.22")

    def test_no_existe(self):
        with self.assertRaises(ValueError):
            elegir_iteracion(ITERS, None, 99)
        with self.assertRaises(ValueError):
            elegir_iteracion(ITERS, 2024, 22)

    def test_no_confunde_22_con_122(self):
        its = [{"name": "Sprint 2026.122", "path": "x"}]
        with self.assertRaises(ValueError):
            elegir_iteracion(its, None, 22)


class HtmlTests(unittest.TestCase):
    def test_html_a_texto(self):
        self.assertEqual(html_a_texto("<div>Uno &amp; dos</div><div>Tres<br>cuatro</div>"), "Uno & dos\nTres\ncuatro")
        self.assertEqual(html_a_texto(None), "")
        self.assertEqual(html_a_texto("<div></div><div>&nbsp;</div>"), "")


class AgruparTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id": 3, "type": "Task", "title": "T3", "description": "<div>d3</div>", "state": "Closed",
             "estimated": 4, "completed": 4, "remaining": 0, "parentId": 10},
            {"id": 1, "type": "Task", "title": "T1", "description": None, "state": "Active",
             "estimated": 2.5, "completed": None, "remaining": 2.5, "parentId": 20},
            {"id": 2, "type": "Task", "title": "Huérfana", "state": "New", "parentId": None},
            {"id": 9, "type": "Bug", "title": "No es tarea", "parentId": None},
        ]
        self.padres = [{"id": 10, "title": "Zeta", "type": "Bug"}, {"id": 20, "title": "alfa", "type": "Bug"}]

    def test_agrupa_ordena_y_excluye_no_tasks(self):
        g = agrupar_por_padre(self.items, self.padres)
        self.assertEqual([x["padre"] and x["padre"]["titulo"] for x in g], ["alfa", "Zeta", None])
        self.assertEqual(g[1]["tareas"][0]["descripcion"], "d3")
        self.assertNotIn("No es tarea", str(g))
        t1 = g[0]["tareas"][0]
        self.assertEqual((t1["estimado"], t1["completado"], t1["restante"]), (2.5, 0.0, 2.5))

    def test_totales(self):
        t = totales(agrupar_por_padre(self.items, self.padres))
        self.assertEqual(t, {"tareas": 3, "estimado": 6.5, "completado": 4.0, "restante": 2.5})

    def test_padre_desconocido_no_rompe(self):
        g = agrupar_por_padre([{"id": 1, "type": "Task", "title": "x", "parentId": 77}], [])
        self.assertEqual(g[0]["padre"]["titulo"], "")


if __name__ == "__main__":
    unittest.main()
