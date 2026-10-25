"""Pruebas de los días de aviso (sin red ni credenciales): python -m unittest test_dias_aviso"""
import unittest

from dias_aviso import DIAS_AVISO_POR_DEFECTO, dias_a_texto, dias_de_aviso


class DiasDeAvisoTest(unittest.TestCase):
    def test_sin_dato_o_ilegible_es_lunes_a_sabado(self):
        for valor in (None, "", "   ", "basura", "9,10", 5, {}):
            self.assertEqual(dias_de_aviso(valor), DIAS_AVISO_POR_DEFECTO, repr(valor))

    def test_lee_texto_y_listas(self):
        self.assertEqual(dias_de_aviso("0,1,2,3,4,5"), [0, 1, 2, 3, 4, 5])
        self.assertEqual(dias_de_aviso("6, 2,2"), [2, 6])
        self.assertEqual(dias_de_aviso([4, 0]), [0, 4])

    def test_ignora_lo_invalido_y_conserva_lo_valido(self):
        self.assertEqual(dias_de_aviso("1,x,8,3"), [1, 3])

    def test_ida_y_vuelta(self):
        self.assertEqual(dias_a_texto([5, 0, 5, 3]), "0,3,5")
        self.assertEqual(dias_de_aviso(dias_a_texto([6, 1])), [1, 6])


if __name__ == "__main__":
    unittest.main()
