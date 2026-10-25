"""
Pruebas del módulo «🔐 Permisos y Accesos» con el motor de pruebas de Streamlit (AppTest).
No necesitan login ni red: Supabase se simula con ESTADO, que sobrevive entre recargas
como lo haría la base real.

    python -m unittest test_panel_permisos -v
"""
import copy
import unittest

from streamlit.testing.v1 import AppTest

EMPLEADOS_BASE = [
    {"empleado_id": "EMP-1", "nombre_completo": "Ana Directora", "telefono": "+525511111111",
     "estado": "ACTIVO", "obra_actual": "Torre Norte",
     "permisos": ["CONTROL_ASISTENCIA", "ENVIAR_AVISOS", "MI_CUADRILLA", "REGISTRO_CON_FOTO", "REPORTE_SEMANAL"]},
    {"empleado_id": "EMP-2", "nombre_completo": "Beto Obrero", "telefono": "+525522222222",
     "estado": "ACTIVO", "obra_actual": None, "permisos": ["ENVIAR_AVISOS", "REGISTRO_CON_FOTO"]},
    {"empleado_id": "EMP-3", "nombre_completo": "Carla Sin Telefono", "telefono": None,
     "estado": "ACTIVO", "obra_actual": None, "permisos": []},
    {"empleado_id": "EMP-4", "nombre_completo": "Dani Baja", "telefono": "+525544444444",
     "estado": "INACTIVO", "obra_actual": None, "permisos": ["ENVIAR_AVISOS"]},
]

ESTADO = {"empleados": [], "updates": [], "con_columna": True}


def reiniciar(con_columna=True):
    ESTADO["empleados"] = copy.deepcopy(EMPLEADOS_BASE)
    ESTADO["updates"] = []
    ESTADO["con_columna"] = con_columna


class ConsultaFalsa:
    """Imita table('empleados').update(datos).eq(col, valor).execute() y aplica el cambio a ESTADO."""

    def update(self, datos):
        self.datos = datos
        return self

    def eq(self, columna, valor):
        self.columna, self.valor = columna, valor
        return self

    def execute(self):
        for fila in ESTADO["empleados"]:
            if fila[self.columna] == self.valor:
                fila.update(self.datos)
        ESTADO["updates"].append((self.valor, self.datos))


class SupabaseFalso:
    def table(self, nombre):
        assert nombre == "empleados"
        return ConsultaFalsa()


def pagina():
    """Script que corre AppTest: igual que app.py, vuelve a leer los datos en cada recarga."""
    import pandas as pd
    import test_panel_permisos as t
    from panel_permisos import render

    df = pd.DataFrame(t.ESTADO["empleados"])
    if not t.ESTADO["con_columna"]:
        df = df.drop(columns=["permisos"])
    render(t.SupabaseFalso(), df, "18:00")


def abrir(con_columna=True):
    reiniciar(con_columna)
    at = AppTest.from_function(pagina, default_timeout=10)
    at.run()
    assert not at.exception, at.exception
    return at


def textos(elementos):
    return [e.value for e in elementos]


class VistaGeneralTest(unittest.TestCase):
    def test_arranca_sin_cambios_pendientes(self):
        at = abrir()
        self.assertTrue(any("No hay cambios por guardar" in t for t in textos(at.caption)))
        self.assertTrue(any("18:00" in t.value for t in at.info))

    def test_avisa_que_las_urgencias_llegan_al_contratista_si_nadie_las_recibe(self):
        at = abrir()
        self.assertTrue(any("llegan al contratista" in t.value for t in at.info))
        self.assertFalse(any("Nadie recibe el reporte semanal" in t.value for t in at.warning))

    def test_avisa_si_nadie_recibe_el_reporte(self):
        reiniciar()
        ESTADO["empleados"][0]["permisos"] = []
        at = AppTest.from_function(pagina, default_timeout=10).run()
        self.assertTrue(any("Nadie recibe el reporte semanal" in t.value for t in at.warning))
        self.assertTrue(any("Nadie tiene Control de asistencia" in t.value for t in at.warning))

    def test_sin_la_columna_pide_correr_el_sql(self):
        at = abrir(con_columna=False)
        self.assertTrue(any("columna 'permisos'" in t.value for t in at.warning))

    def test_los_inactivos_no_aparecen(self):
        at = abrir()
        opciones = at.multiselect(key="perm_ENVIAR_AVISOS_0").options
        self.assertFalse(any("Dani" in o for o in opciones))


class PorPermisoTest(unittest.TestCase):
    def test_quien_no_tiene_telefono_no_se_ofrece_para_recibir_pero_si_para_el_resto(self):
        at = abrir()
        recibir = at.multiselect(key="perm_REPORTE_SEMANAL_0").options
        resto = at.multiselect(key="perm_ENVIAR_AVISOS_0").options
        self.assertFalse(any("Carla" in o for o in recibir))
        self.assertTrue(any("Carla" in o for o in resto))

    def test_agregar_a_alguien_muestra_el_resumen_y_guarda_solo_ese_cambio(self):
        at = abrir()
        selector = at.multiselect(key="perm_RECIBIR_URGENCIAS_0")
        selector.select("Beto Obrero (+525522222222)").run()
        resumen = " ".join(t.value for t in at.markdown)
        self.assertIn("Beto Obrero", resumen)
        self.assertIn("➕ Recibe las urgencias", resumen)

        at.button(key="perm_guardar_0").click().run()
        self.assertEqual(ESTADO["updates"], [("EMP-2", {"permisos": ["ENVIAR_AVISOS", "RECIBIR_URGENCIAS", "REGISTRO_CON_FOTO"]})])
        self.assertTrue(any("Permisos guardados" in t.value for t in at.success))
        # tras guardar la pantalla arranca limpia: ya no hay cambios y el aviso de urgencias desaparece
        self.assertTrue(any("No hay cambios por guardar" in t for t in textos(at.caption)))
        self.assertFalse(any("llegan al contratista" in t.value for t in at.info))

    def test_quitar_a_alguien(self):
        at = abrir()
        at.multiselect(key="perm_CONTROL_ASISTENCIA_0").unselect("Ana Directora (+525511111111)").run()
        resumen = " ".join(t.value for t in at.markdown)
        self.assertIn("➖ Control de asistencia", resumen)
        at.button(key="perm_guardar_0").click().run()
        self.assertNotIn("CONTROL_ASISTENCIA", ESTADO["empleados"][0]["permisos"])


class PorPersonaTest(unittest.TestCase):
    def test_vista_previa_del_whatsapp_cambia_con_las_casillas(self):
        at = abrir()
        at.selectbox(key="perm_persona_0").select("EMP-1").run()
        menu = " ".join(textos(at.text))
        self.assertIn("2️⃣", menu)
        self.assertIn("Registrar SALIDA", menu)

        at.checkbox(key="perm_chk_EMP-1_ENVIAR_AVISOS_0").uncheck().run()
        menu = " ".join(textos(at.text))
        self.assertNotIn("2️⃣", menu)
        self.assertTrue(any("Cambios por guardar" in t.value for t in at.info))
        self.assertEqual(ESTADO["updates"], [])   # la vista previa no guarda nada

    def test_guardar_a_una_persona(self):
        at = abrir()
        at.selectbox(key="perm_persona_0").select("EMP-3").run()
        at.checkbox(key="perm_chk_EMP-3_MI_CUADRILLA_0").check().run()
        at.button(key="perm_guardar_p_0").click().run()
        self.assertEqual(ESTADO["updates"], [("EMP-3", {"permisos": ["MI_CUADRILLA"]})])

    def test_sin_permisos_se_describe_el_registro_simple(self):
        at = abrir()
        at.selectbox(key="perm_persona_0").select("EMP-3").run()
        resumen = " ".join(t.value for t in at.markdown)
        self.assertIn("sin foto", resumen)
        self.assertIn("cierra su turno solo a las 18:00", resumen)


class TransicionTest(unittest.TestCase):
    def test_quitar_registro_con_foto_a_todos_exige_confirmar(self):
        at = abrir()
        boton = at.button(key="perm_trans_btn_0")
        self.assertTrue(boton.disabled)
        at.checkbox(key="perm_trans_ok_0").check().run()
        at.button(key="perm_trans_btn_0").click().run()
        self.assertEqual({i for i, _ in ESTADO["updates"]}, {"EMP-1", "EMP-2"})
        for fila in ESTADO["empleados"][:2]:
            self.assertNotIn("REGISTRO_CON_FOTO", fila["permisos"])
        # lo demás no se toca
        self.assertIn("ENVIAR_AVISOS", ESTADO["empleados"][1]["permisos"])

    def test_se_puede_dejar_el_permiso_a_una_excepcion(self):
        at = abrir()
        at.multiselect(key="perm_trans_exc_0").select("Ana Directora (+525511111111)").run()
        at.checkbox(key="perm_trans_ok_0").check().run()
        at.button(key="perm_trans_btn_0").click().run()
        self.assertEqual([i for i, _ in ESTADO["updates"]], ["EMP-2"])
        self.assertIn("REGISTRO_CON_FOTO", ESTADO["empleados"][0]["permisos"])


if __name__ == "__main__":
    unittest.main()
