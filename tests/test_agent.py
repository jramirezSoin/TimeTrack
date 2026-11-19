import unittest
from datetime import date
from types import SimpleNamespace

from timetrack.agent import (
    ActividadExt, DiaExt, Extraccion, ExtraccionError, parse_prose, to_plan,
)


def ext(*dias):
    return Extraccion(dias=list(dias))


def dia(fecha, *acts):
    return DiaExt(fecha=fecha, actividades=list(acts))


def act(desc="x", horas=4.0, inc=None):
    return ActividadExt(descripcion=desc, horas=horas, incidente=inc)


class FakeClient:
    def __init__(self, parsed=None, stop_reason="end_turn"):
        self.llamadas = []
        self._resp = SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason)
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kw):
        self.llamadas.append(kw)
        return self._resp


class ToPlanTests(unittest.TestCase):
    def test_convierte_fechas_dd_mm_yyyy_y_actividades(self):
        plan = to_plan(ext(dia("29-10-2026", act("a", 4), act("b", 4, "100001273"))))
        self.assertEqual(plan.dias[0].fecha, date(2026, 10, 29))
        self.assertEqual(plan.dias[0].actividades[1].incidente, "100001273")

    def test_sin_horas_es_error_y_no_las_inventa(self):
        with self.assertRaises(ExtraccionError) as cm:
            to_plan(ext(dia("29-10-2026", act("a", None), act("b", 8))))
        self.assertIn("29-10-2026", str(cm.exception))
        self.assertIn("sin horas", str(cm.exception))

    def test_fecha_invalida_es_error(self):
        with self.assertRaises(ExtraccionError) as cm:
            to_plan(ext(dia("ayer", act())))
        self.assertIn("fecha no reconocida", str(cm.exception))

    def test_sin_dias_es_error(self):
        with self.assertRaises(ExtraccionError):
            to_plan(ext())


class ParseProseTests(unittest.TestCase):
    def test_usa_la_api_con_salida_estructurada(self):
        client = FakeClient(ext(dia("29-10-2026", act("a", 8))))
        plan = parse_prose("29-10-2026\na 8", client=client, model="m-test")
        self.assertEqual(plan.dias[0].total_horas, 8)
        llamada = client.llamadas[0]
        self.assertEqual(llamada["model"], "m-test")
        self.assertIs(llamada["output_format"], Extraccion)

    def test_verbose_informa_etapas_en_stderr(self):
        import io
        from contextlib import redirect_stderr
        client = FakeClient(ext(dia("29-10-2026", act("a", 8))))
        buf = io.StringIO()
        with redirect_stderr(buf):
            parse_prose("29-10-2026\na 8", client=client, verbose=True)
        salida = buf.getvalue()
        self.assertIn("Enviando 2 línea(s)", salida)
        self.assertIn("Respuesta recibida", salida)
        self.assertIn("1 día(s), 1 actividad(es)", salida)

    def test_progress_recibe_etapas_y_no_escribe_en_consola(self):
        import io
        from contextlib import redirect_stderr
        client = FakeClient(ext(dia("29-10-2026", act("a", 8))))
        etapas, buf = [], io.StringIO()
        with redirect_stderr(buf):
            parse_prose("29-10-2026\na 8", client=client, progress=etapas.append)
        self.assertEqual(buf.getvalue(), "")
        self.assertTrue(etapas[0].startswith("[agente] Enviando 2 línea(s)"))
        self.assertTrue(etapas[-1].endswith("1 día(s), 1 actividad(es) interpretadas."))

    def test_silencioso_por_defecto(self):
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            parse_prose("x", client=FakeClient(ext(dia("29-10-2026", act("a", 8)))))
        self.assertEqual(buf.getvalue(), "")

    def test_texto_vacio(self):
        with self.assertRaises(ExtraccionError):
            parse_prose("  ", client=FakeClient())

    def test_refusal_y_truncado_son_errores(self):
        for motivo in ("refusal", "max_tokens"):
            with self.assertRaises(ExtraccionError):
                parse_prose("x", client=FakeClient(stop_reason=motivo))

    def test_sin_salida_parseada(self):
        with self.assertRaises(ExtraccionError):
            parse_prose("x", client=FakeClient(parsed=None))


if __name__ == "__main__":
    unittest.main()
