"""Pruebas del respaldo en Excel (sin red ni credenciales): python -X utf8 -m unittest test_excel_respaldo

Regresión: tras agregar `empleados.permisos` (lista), «Descargar Copia de Seguridad Total» fallaba porque
`pd.notna(lista)` devuelve un arreglo y el autoajuste de columnas no lo admite."""
import io
import unittest

import openpyxl
import pandas as pd

from reportes import aplicar_formato_hoja, listas_a_texto


def leer_hoja(buffer, nombre):
    hoja = openpyxl.load_workbook(io.BytesIO(buffer.getvalue()))[nombre]
    return [[c.value for c in fila] for fila in hoja.iter_rows()]


def escribir(df, nombre="Hoja"):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        aplicar_formato_hoja(writer, df, nombre, color_header="#0E1C36")
    return buffer


class RespaldoExcelTest(unittest.TestCase):
    def setUp(self):
        self.empleados = pd.DataFrame({
            "empleado_id": ["EMP-1", "EMP-2", "EMP-3", "EMP-4"],
            "nombre_completo": ["Sara", "Fabio", "Alma", None],
            "permisos": [["REGISTRO_CON_FOTO", "ENVIAR_AVISOS"], [], ["MI_CUADRILLA"], None],
        })

    def test_directorio_con_permisos_en_lista_se_exporta_como_texto(self):
        filas = leer_hoja(escribir(self.empleados, "Directorio Completo"), "Directorio Completo")
        self.assertEqual(filas[0], ["empleado_id", "nombre_completo", "permisos"])
        self.assertEqual(filas[1][2], "REGISTRO_CON_FOTO, ENVIAR_AVISOS")
        self.assertIn(filas[2][2], (None, ""))   # lista vacía = celda en blanco
        self.assertEqual(filas[3][2], "MI_CUADRILLA")
        self.assertIsNone(filas[4][2])           # sin dato sigue en blanco

    def test_no_modifica_el_dataframe_original(self):
        escribir(self.empleados)
        self.assertEqual(self.empleados.loc[0, "permisos"], ["REGISTRO_CON_FOTO", "ENVIAR_AVISOS"])

    def test_sin_listas_queda_igual(self):
        df = pd.DataFrame({"a": [1, 2], "b": ["x", None]})
        pd.testing.assert_frame_equal(listas_a_texto(df), df)
        self.assertEqual(leer_hoja(escribir(df), "Hoja")[1], [1, "x"])

    def test_diccionarios_y_tuplas_tambien_pasan_a_texto(self):
        df = pd.DataFrame({"datos": [{"faltan": ["foto"]}, ("a", "b")]})
        filas = leer_hoja(escribir(df), "Hoja")
        self.assertEqual(filas[1][0], '{"faltan": ["foto"]}')
        self.assertEqual(filas[2][0], "a, b")

    def test_hoja_vacia_no_falla(self):
        escribir(pd.DataFrame({"Aviso": []}))


if __name__ == "__main__":
    unittest.main()
