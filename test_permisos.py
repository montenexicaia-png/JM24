"""
Pruebas de `permisos.py`. No usan red ni credenciales (Supabase se simula).

    python -m unittest test_permisos -v
"""
import unittest

import permisos
from permisos import (
    CATALOGO, POR_CODIGO, REPORTE_SEMANAL, CONTROL_ASISTENCIA, ENVIAR_AVISOS, MI_CUADRILLA,
    REGISTRO_CON_FOTO, RECIBIR_URGENCIAS, FOTO_GRUPAL, permisos_de, tiene_permiso, empleados_con_permiso,
    telefonos_con_permiso, calcular_cambios, texto_menu_inicio, texto_menu_en_turno, comandos_especiales,
    que_puede_hacer, permisos_al_cambiar_de_rol, elegir_destinatarios_urgencia,
)


class ConsultaFalsa:
    """Imita la cadena table().select().eq().contains().execute() y recuerda cómo se le llamó."""

    def __init__(self, filas, llamadas):
        self.filas, self.llamadas = filas, llamadas

    def select(self, columnas):
        self.llamadas.append(("select", columnas))
        return self

    def eq(self, columna, valor):
        self.llamadas.append(("eq", columna, valor))
        return self

    def contains(self, columna, valor):
        self.llamadas.append(("contains", columna, valor))
        return self

    def execute(self):
        class Respuesta:
            data = self.filas
        return Respuesta()


class SupabaseFalso:
    def __init__(self, filas=None, falla=False):
        self.filas, self.falla, self.llamadas = filas or [], falla, []

    def table(self, nombre):
        if self.falla:
            raise ConnectionError("sin conexión")
        self.llamadas.append(("table", nombre))
        return ConsultaFalsa(self.filas, self.llamadas)


class CatalogoTest(unittest.TestCase):
    def test_codigos_unicos_y_sin_vacios(self):
        codigos = [p.codigo for p in CATALOGO]
        self.assertEqual(len(codigos), len(set(codigos)))
        for p in CATALOGO:
            self.assertTrue(p.nombre and p.descripcion and p.icono, p.codigo)

    def test_constantes_coinciden_con_el_catalogo(self):
        for nombre in ("REPORTE_SEMANAL", "CONTROL_ASISTENCIA", "RECIBIR_URGENCIAS", "ENVIAR_AVISOS",
                       "MI_CUADRILLA", "FOTO_GRUPAL", "REGISTRO_CON_FOTO"):
            self.assertEqual(getattr(permisos, nombre), nombre)
            self.assertIn(nombre, POR_CODIGO)


class TienePermisoTest(unittest.TestCase):
    def test_con_y_sin_permiso(self):
        emp = {"permisos": [ENVIAR_AVISOS, REPORTE_SEMANAL]}
        self.assertTrue(tiene_permiso(emp, ENVIAR_AVISOS))
        self.assertFalse(tiene_permiso(emp, CONTROL_ASISTENCIA))

    def test_sin_columna_nula_o_sin_fila_no_tiene_nada(self):
        self.assertEqual(permisos_de({}), set())
        self.assertEqual(permisos_de({"permisos": None}), set())
        self.assertEqual(permisos_de(None), set())
        self.assertFalse(tiene_permiso(None, ENVIAR_AVISOS))

    def test_arreglo_como_texto(self):
        self.assertEqual(permisos_de({"permisos": '{ENVIAR_AVISOS,"MI_CUADRILLA"}'}),
                         {"ENVIAR_AVISOS", "MI_CUADRILLA"})
        self.assertEqual(permisos_de({"permisos": "{}"}), set())


    def test_valor_nan_de_un_dataframe_cuenta_como_sin_permisos(self):
        self.assertEqual(permisos_de({"permisos": float("nan")}), set())


    def test_fila_de_pandas(self):
        import pandas as pd
        fila = pd.DataFrame([{"empleado_id": "E1", "permisos": [ENVIAR_AVISOS]}]).iloc[0]
        self.assertEqual(permisos_de(fila), {ENVIAR_AVISOS})


class RolesTest(unittest.TestCase):
    def test_al_nombrar_director_se_agregan_sus_permisos_sin_quitar_nada(self):
        despues = permisos_al_cambiar_de_rol({ENVIAR_AVISOS}, "TRABAJADOR", "DIRECTOR")
        self.assertEqual(despues, {ENVIAR_AVISOS, REPORTE_SEMANAL, CONTROL_ASISTENCIA, RECIBIR_URGENCIAS, MI_CUADRILLA})

    def test_el_director_recibe_urgencias_y_no_foto_grupal_ni_registro_con_foto(self):
        despues = permisos_al_cambiar_de_rol(set(), "TRABAJADOR", "DIRECTOR")
        self.assertIn(RECIBIR_URGENCIAS, despues)
        self.assertNotIn(FOTO_GRUPAL, despues)
        self.assertNotIn(REGISTRO_CON_FOTO, despues)

    def test_encargado_recibe_foto_grupal(self):
        despues = permisos_al_cambiar_de_rol(set(), None, "ENCARGADO")
        self.assertEqual(despues, {CONTROL_ASISTENCIA, MI_CUADRILLA, FOTO_GRUPAL, ENVIAR_AVISOS})

    def test_sin_cambio_de_rol_no_se_devuelve_lo_que_se_quito_a_mano(self):
        actuales = {REPORTE_SEMANAL}   # al director se le quitaron los demás
        self.assertEqual(permisos_al_cambiar_de_rol(actuales, "DIRECTOR", "DIRECTOR"), actuales)

    def test_degradar_a_trabajador_no_quita_nada(self):
        actuales = {REPORTE_SEMANAL, RECIBIR_URGENCIAS}
        self.assertEqual(permisos_al_cambiar_de_rol(actuales, "DIRECTOR", "TRABAJADOR"), actuales)

    def test_rol_anterior_nulo_o_nan_cuenta_como_trabajador(self):
        self.assertEqual(permisos_al_cambiar_de_rol(set(), float("nan"), "TRABAJADOR"), set())
        self.assertIn(MI_CUADRILLA, permisos_al_cambiar_de_rol(set(), float("nan"), "ENCARGADO"))


class UrgenciasTest(unittest.TestCase):
    DIRECTOR_1, DIRECTOR_2, CONTRATISTA = "+525511111111", "+525522222222", "525533333333"

    def test_llega_a_todos_los_directores(self):
        self.assertEqual(
            elegir_destinatarios_urgencia([self.DIRECTOR_1, self.DIRECTOR_2], self.CONTRATISTA, "+525599999999"),
            [self.DIRECTOR_1, self.DIRECTOR_2])

    def test_no_se_avisa_a_quien_reporta_aunque_el_numero_venga_escrito_distinto(self):
        # el webhook entrega 52 + 10 dígitos; en la base está +52…; Meta a veces manda 521…
        for reporta in ("525511111111", "+525511111111", "5215511111111"):
            self.assertEqual(
                elegir_destinatarios_urgencia([self.DIRECTOR_1, self.DIRECTOR_2], self.CONTRATISTA, reporta),
                [self.DIRECTOR_2], reporta)

    def test_si_el_unico_destinatario_es_quien_reporta_va_al_contratista(self):
        self.assertEqual(elegir_destinatarios_urgencia([self.DIRECTOR_1], self.CONTRATISTA, "525511111111"),
                         [self.CONTRATISTA])

    def test_sin_nadie_con_el_permiso_va_al_contratista(self):
        self.assertEqual(elegir_destinatarios_urgencia([], self.CONTRATISTA, "525599999999"), [self.CONTRATISTA])

    def test_si_quien_reporta_es_el_contratista_no_se_le_manda_a_si_mismo(self):
        self.assertEqual(elegir_destinatarios_urgencia([], self.CONTRATISTA, "525533333333"), [])

    def test_sin_contratista_configurado(self):
        self.assertEqual(elegir_destinatarios_urgencia([], None, "525599999999"), [])


class CambiosTest(unittest.TestCase):
    def test_solo_aparece_quien_cambia(self):
        actuales = {"A": {"X", "Y"}, "B": {"X"}, "C": set()}
        deseados = {"A": {"X", "Z"}, "B": {"X"}, "C": set()}
        self.assertEqual(calcular_cambios(actuales, deseados), {"A": ({"Z"}, {"Y"})})

    def test_sin_cambios(self):
        self.assertEqual(calcular_cambios({"A": {"X"}}, {"A": {"X"}}), {})
        self.assertEqual(calcular_cambios({"A": {"X"}}, {}), {})


class MensajesTest(unittest.TestCase):
    def test_menu_en_turno_sin_permiso_solo_ofrece_la_salida(self):
        menu = texto_menu_en_turno("Beto", set())
        self.assertIn("4️⃣", menu)
        self.assertNotIn("2️⃣", menu)
        self.assertNotIn("3️⃣", menu)

    def test_menu_en_turno_con_permiso_ofrece_aviso_y_urgencia(self):
        menu = texto_menu_en_turno("Beto", {ENVIAR_AVISOS})
        for opcion in ("2️⃣", "3️⃣", "4️⃣"):
            self.assertIn(opcion, menu)

    def test_menu_de_inicio(self):
        self.assertIn("Hola, Beto", texto_menu_inicio("Beto"))
        self.assertIn("1️⃣", texto_menu_inicio("Beto"))

    def test_comandos_especiales(self):
        self.assertEqual(comandos_especiales(set()), [])
        self.assertEqual(comandos_especiales({CONTROL_ASISTENCIA, MI_CUADRILLA}), ["AVISAR", "MI CUADRILLA"])

    def test_que_puede_hacer_distingue_registro_simple_y_con_foto(self):
        simple = " ".join(que_puede_hacer(set(), "18:00"))
        self.assertIn("sin foto", simple)
        self.assertIn("a las 18:00", simple)
        completo = " ".join(que_puede_hacer({REGISTRO_CON_FOTO}, "18:00"))
        self.assertIn("ubicación y foto", completo)
        self.assertNotIn("sin foto", completo)

    def test_que_puede_hacer_lista_lo_que_tiene(self):
        frases = que_puede_hacer({REPORTE_SEMANAL}, "18:00")
        self.assertTrue(any("PDF" in f for f in frases))


class DestinatariosTest(unittest.TestCase):
    def test_consulta_solo_activos_con_el_permiso(self):
        db = SupabaseFalso([{"telefono": "+521"}])
        empleados_con_permiso(db, CONTROL_ASISTENCIA)
        self.assertIn(("table", "empleados"), db.llamadas)
        self.assertIn(("eq", "estado", "ACTIVO"), db.llamadas)
        self.assertIn(("contains", "permisos", [CONTROL_ASISTENCIA]), db.llamadas)

    def test_telefonos_sin_repetidos_ni_vacios(self):
        db = SupabaseFalso([
            {"telefono": "+525511111111"}, {"telefono": None}, {"telefono": "  "},
            {"telefono": "+525511111111"}, {"telefono": " +525522222222 "},
        ])
        self.assertEqual(telefonos_con_permiso(db, REPORTE_SEMANAL),
                         ["+525511111111", "+525522222222"])

    def test_lista_vacia(self):
        self.assertEqual(telefonos_con_permiso(SupabaseFalso([]), REPORTE_SEMANAL), [])

    def test_si_supabase_falla_se_propaga_para_que_quien_llama_decida(self):
        with self.assertRaises(ConnectionError):
            telefonos_con_permiso(SupabaseFalso(falla=True), REPORTE_SEMANAL)


if __name__ == "__main__":
    unittest.main()
