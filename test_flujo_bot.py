"""
Pruebas del flujo del bot por permisos (registro simple vs con foto, comandos autorizados) y del
cierre automático de turnos. No usan red ni credenciales: Supabase y el scheduler se reemplazan
ANTES de importar `main`, así que no se arranca ningún reloj ni se manda ningún WhatsApp.

    python -m unittest test_flujo_bot -v
"""
import datetime
import sys
import types
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

MX = ZoneInfo("America/Mexico_City")


# ---------- Supabase en memoria ----------
class Consulta:
    def __init__(self, bd, tabla):
        self.bd, self.tabla = bd, tabla
        self.operacion, self.datos, self.filtros, self.orden, self.rango = "select", None, [], None, None

    def select(self, columnas="*"):
        return self

    def insert(self, fila):
        self.operacion, self.datos = "insert", fila
        return self

    def upsert(self, fila):
        self.operacion, self.datos = "upsert", fila
        return self

    def update(self, datos):
        self.operacion, self.datos = "update", datos
        return self

    def delete(self):
        self.operacion = "delete"
        return self

    def eq(self, columna, valor):
        self.filtros.append(lambda f: f.get(columna) == valor)
        return self

    def neq(self, columna, valor):
        self.filtros.append(lambda f: f.get(columna) != valor)
        return self

    def gte(self, columna, valor):
        self.filtros.append(lambda f: f.get(columna) is not None and f.get(columna) >= valor)
        return self

    def lte(self, columna, valor):
        self.filtros.append(lambda f: f.get(columna) is not None and f.get(columna) <= valor)
        return self

    def in_(self, columna, valores):
        self.filtros.append(lambda f: f.get(columna) in valores)
        return self

    def contains(self, columna, valores):
        self.filtros.append(lambda f: set(valores) <= set(f.get(columna) or []))
        return self

    def order(self, columna, desc=False):
        self.orden = (columna, desc)
        return self

    def range(self, desde, hasta):
        self.rango = (desde, hasta)
        return self

    def execute(self):
        filas = self.bd.tablas.setdefault(self.tabla, [])
        if self.operacion == "insert":
            filas.append(dict(self.datos))
            return SimpleNamespace(data=[dict(self.datos)])
        if self.operacion == "upsert":   # la única tabla con upsert es estados_conversacion (clave: telefono)
            for f in filas:
                if f["telefono"] == self.datos["telefono"]:
                    f.update(self.datos)
                    break
            else:
                filas.append(dict(self.datos))
            return SimpleNamespace(data=[dict(self.datos)])
        coincidentes = [f for f in filas if all(p(f) for p in self.filtros)]
        if self.operacion == "update":
            for f in coincidentes:
                f.update(self.datos)
            return SimpleNamespace(data=[dict(f) for f in coincidentes])
        if self.operacion == "delete":
            self.bd.tablas[self.tabla] = [f for f in filas if f not in coincidentes]
            return SimpleNamespace(data=[])
        if self.orden:
            coincidentes = sorted(coincidentes, key=lambda f: f.get(self.orden[0]) or "", reverse=self.orden[1])
        if self.rango:
            coincidentes = coincidentes[self.rango[0]:self.rango[1] + 1]
        return SimpleNamespace(data=[dict(f) for f in coincidentes])


class BDFalsa:
    def __init__(self):
        self.tablas = {}

    def table(self, nombre):
        return Consulta(self, nombre)

    def filas(self, tabla):
        return self.tablas.get(tabla, [])


BD = BDFalsa()
main = None


def importar_main():
    """Importa main con Supabase y scheduler falsos y la red bloqueada."""
    global main
    if main is not None:
        return main
    falso = types.ModuleType("database")
    falso.supabase = BD
    falso.supabase_panel = None
    falso.bot_esta_activo = lambda: True
    falso.registrar_consumo_mensaje = lambda: None
    sys.modules["database"] = falso

    import apscheduler.schedulers.background as fondo

    class SchedulerFalso:
        def add_job(self, *args, **kwargs):
            pass

        def start(self):
            pass

    fondo.BackgroundScheduler = SchedulerFalso

    import requests

    def sin_red(*args, **kwargs):
        raise AssertionError("Las pruebas no deben mandar nada por la red")

    requests.post = sin_red
    import main as modulo
    main = modulo
    return main


def mx(dia, hora, minuto=0, mes=10):
    return datetime.datetime(2026, mes, dia, hora, minuto, tzinfo=MX)


EMPLEADOS = [
    {"empleado_id": "EMP-1", "nombre_completo": "Sara Simple", "telefono": "+525511110001", "estado": "ACTIVO",
     "obra_actual": "Torre Norte", "permisos": []},
    {"empleado_id": "EMP-2", "nombre_completo": "Fabio Foto", "telefono": "+525511110002", "estado": "ACTIVO",
     "obra_actual": "Torre Norte", "permisos": ["REGISTRO_CON_FOTO", "ENVIAR_AVISOS"]},
    {"empleado_id": "EMP-3", "nombre_completo": "Alma Avisos", "telefono": "+525511110003", "estado": "ACTIVO",
     "obra_actual": None, "permisos": ["ENVIAR_AVISOS"]},
    {"empleado_id": "EMP-4", "nombre_completo": "Jefa Control", "telefono": "+525511110004", "estado": "ACTIVO",
     "obra_actual": None, "permisos": ["CONTROL_ASISTENCIA", "MI_CUADRILLA"]},
    {"empleado_id": "EMP-5", "nombre_completo": "Baja Control", "telefono": "+525511110005", "estado": "INACTIVO",
     "obra_actual": None, "permisos": ["CONTROL_ASISTENCIA", "MI_CUADRILLA"]},
]
TEL = {e["empleado_id"]: e["telefono"] for e in EMPLEADOS}


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.main = importar_main()
        BD.tablas = {"empleados": [dict(e) for e in EMPLEADOS],
                     "configuracion": [{"id": 1, "hora_corte_salida": "18:00"}]}

    def escribir(self, emp_id, texto):
        return self.main.procesar_mensaje_whatsapp(TEL[emp_id], texto)

    def estado(self, emp_id):
        for f in BD.filas("estados_conversacion"):
            if f["telefono"] == TEL[emp_id]:
                return f["estado"]
        return None

    def registros(self, tipo=None):
        return [r for r in BD.filas("registros_asistencia") if tipo is None or r["tipo_registro"] == tipo]


class RegistroSimpleTest(BaseTest):
    def test_entrada_con_ubicacion_sin_foto_y_salida_con_la_palabra_salida(self):
        self.assertIn("Ubicación", self.escribir("EMP-1", "1"))
        respuesta = self.escribir("EMP-1", "19.4326,-99.1332")
        self.assertIn("ENTRADA quedó registrada", respuesta)
        self.assertEqual(self.estado("EMP-1"), "EN_TURNO")
        entrada = self.registros("ENTRADA")[0]
        self.assertEqual(entrada["empleado_id"], "EMP-1")
        self.assertNotIn("foto_url", entrada)
        self.assertIn("google.com/maps?q=19.4326,-99.1332", entrada["ubicacion"])

        respuesta = self.escribir("EMP-1", "SALIDA")
        self.assertIn("SALIDA quedó registrada", respuesta)
        salida = self.registros("SALIDA")[0]
        self.assertEqual(salida["empleado_id"], "EMP-1")
        for campo in ("foto_url", "latitud", "avances", "pendientes"):
            self.assertNotIn(campo, salida)
        self.assertIsNone(self.estado("EMP-1"))   # turno cerrado: mañana vuelve a empezar

    def test_tambien_sirve_el_numero_4(self):
        self.escribir("EMP-1", "1")
        self.escribir("EMP-1", "19.4,-99.1")
        self.assertIn("SALIDA quedó registrada", self.escribir("EMP-1", "4"))

    def test_sin_permiso_no_ve_ni_puede_usar_avisos_y_urgencias(self):
        self.escribir("EMP-1", "1")
        self.escribir("EMP-1", "19.4,-99.1")
        menu = self.escribir("EMP-1", "hola")
        self.assertNotIn("2️⃣", menu)
        self.assertNotIn("3️⃣", menu)
        self.assertIn("4️⃣", menu)
        for opcion in ("2", "3"):
            self.assertNotIn("MODO", self.escribir("EMP-1", opcion))
            self.assertEqual(self.estado("EMP-1"), "EN_TURNO")

    def test_salida_sin_turno_abierto_explica_en_vez_de_mostrar_el_menu(self):
        respuesta = self.escribir("EMP-1", "salida")
        self.assertIn("No tienes ningún turno abierto", respuesta)
        self.assertEqual(self.registros(), [])

    def test_sin_estado_muestra_el_menu_de_inicio(self):
        self.assertIn("Registrar ENTRADA", self.escribir("EMP-1", "hola"))

    def test_ubicacion_mal_enviada_no_registra_nada(self):
        self.escribir("EMP-1", "1")
        self.assertIn("clip", self.escribir("EMP-1", "estoy llegando"))
        self.assertEqual(self.registros(), [])


class AvisosYUrgenciasTest(BaseTest):
    def test_con_permiso_se_pueden_reportar(self):
        self.escribir("EMP-3", "1")
        self.escribir("EMP-3", "19.4,-99.1")
        menu = self.escribir("EMP-3", "hola")
        self.assertIn("2️⃣", menu)
        self.assertIn("3️⃣", menu)
        self.assertIn("MODO AVISO", self.escribir("EMP-3", "2"))
        self.assertIn("Aviso registrado", self.escribir("EMP-3", "Falta cemento"))
        self.assertIn("MODO URGENCIA", self.escribir("EMP-3", "3"))
        self.assertIn("REPORTE URGENTE ENVIADO", self.escribir("EMP-3", "Se cayó un andamio"))
        self.assertEqual([r["estado"] for r in BD.filas("reportes_incidentes")], ["AVISO", "URGENTE"])


class RegistroConFotoTest(BaseTest):
    def test_conserva_el_flujo_con_foto_avances_y_pendientes(self):
        self.escribir("EMP-2", "1")
        self.assertIn("Foto", self.escribir("EMP-2", "19.4,-99.1"))
        self.assertEqual(self.estado("EMP-2"), "ESPERANDO_FOTO_ENTRADA")
        self.assertEqual(self.registros(), [])   # todavía no se registra: falta la foto
        self.assertIn("ENTRADA quedó registrada", self.escribir("EMP-2", "FOTO|https://x/f.jpg"))
        self.assertEqual(self.registros("ENTRADA")[0]["foto_url"], "https://x/f.jpg")

        self.assertIn("INICIANDO SALIDA", self.escribir("EMP-2", "SALIDA"))
        self.assertEqual(self.estado("EMP-2"), "ESPERANDO_UBICACION_SALIDA")
        self.escribir("EMP-2", "19.4,-99.1")
        self.escribir("EMP-2", "FOTO|https://x/s.jpg")
        self.escribir("EMP-2", "Colamos la losa")
        self.assertIn("SALIDA oficial", self.escribir("EMP-2", "Armar muros"))
        salida = self.registros("SALIDA")[0]
        self.assertEqual((salida["avances"], salida["pendientes"], salida["foto_url"]),
                         ("Colamos la losa", "Armar muros", "https://x/s.jpg"))


class ComandosTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.avisados = []
        self.main.disparar_avisos_rezagados = lambda tel: self.avisados.append(tel)
        self.main.enviar_mensaje_whatsapp = lambda tel, msg: None
        self.main.registrar_consumo_mensaje = lambda: None
        self.main.generar_reporte_cuadrilla = lambda emp: ("Resumen", [])

    def test_avisar_solo_con_control_de_asistencia_y_activo(self):
        self.assertIn("Escaneo y envío", self.escribir("EMP-4", "AVISAR"))
        self.assertEqual(self.avisados, [TEL["EMP-4"]])
        for emp_id in ("EMP-1", "EMP-2", "EMP-5"):   # sin permiso, con otro permiso, y dado de baja
            self.assertIn("No tienes autorización", self.escribir(emp_id, "AVISAR"), emp_id)
        self.assertEqual(self.avisados, [TEL["EMP-4"]])

    def test_mi_cuadrilla_solo_con_el_permiso_y_activo(self):
        self.assertIsNone(self.escribir("EMP-4", "MI CUADRILLA"))   # el reporte va por mensaje aparte
        for emp_id in ("EMP-1", "EMP-5"):
            self.assertIn("No tienes autorización", self.escribir(emp_id, "MI CUADRILLA"), emp_id)


class ReporteSemanalTest(BaseTest):
    def test_tolera_fechas_con_y_sin_fraccion_de_segundo(self):
        """Regresión: el cierre automático guarda fechas sin fracción (…:00:00) y el resto con ella
        (…:03:07.123456); pandas 3 fallaba al mezclarlas y el reporte/panel dejaban de abrir."""
        ahora = datetime.datetime.now(MX)
        BD.tablas["empleados"][3]["permisos"] = ["REPORTE_SEMANAL"]
        BD.tablas["registros_asistencia"] = [
            {"empleado_id": "EMP-1", "tipo_registro": "ENTRADA", "obra": "Torre Norte",
             "fecha_hora": ahora.replace(hour=8, minute=3, second=7, microsecond=123456).isoformat()},
            {"empleado_id": "EMP-1", "tipo_registro": "SALIDA", "obra": "Torre Norte", "metodo": "AUTO",
             "fecha_hora": ahora.replace(hour=18, minute=0, second=0, microsecond=0).isoformat()},
        ]
        enviados = []
        self.main.enviar_documento_whatsapp_plantilla = lambda tel, *args: enviados.append(tel) or True
        self.main.disparar_reporte_semanal_director()
        self.assertEqual(enviados, [TEL["EMP-4"]])


class RelojDeAvisosTest(BaseTest):
    """Recordatorios de entrada/salida: 24 oct 2026 = sábado, 25 = domingo, 26 = lunes."""

    def setUp(self):
        super().setUp()
        BD.tablas["configuracion"] = [{"id": 1, "hora_corte_entrada": "08:15", "hora_corte_salida": "18:00"}]
        self.main.ultimo_aviso_entrada = self.main.ultimo_aviso_salida = None
        self.enviados = []
        self.main.enviar_plantilla_whatsapp = lambda tel, plantilla, texto: self.enviados.append((tel, texto))

    def test_sabado_si_avisa_a_quien_tiene_control_de_asistencia(self):
        self.main.checar_reloj_bot(ahora=mx(24, 8, 15))
        self.assertEqual(self.enviados, [(TEL["EMP-4"], "la mañana")])
        self.main.checar_reloj_bot(ahora=mx(24, 18, 0))
        self.assertEqual(self.enviados[-1], (TEL["EMP-4"], "la tarde"))

    def test_domingo_no_avisa_por_defecto(self):
        self.main.checar_reloj_bot(ahora=mx(25, 8, 15))
        self.main.checar_reloj_bot(ahora=mx(25, 18, 0))
        self.assertEqual(self.enviados, [])

    def test_domingo_si_avisa_si_se_activa_en_el_panel(self):
        BD.tablas["configuracion"][0]["dias_aviso"] = "0,1,2,3,4,5,6"
        self.main.checar_reloj_bot(ahora=mx(25, 8, 15))
        self.assertEqual(self.enviados, [(TEL["EMP-4"], "la mañana")])

    def test_respeta_los_dias_elegidos(self):
        BD.tablas["configuracion"][0]["dias_aviso"] = "0,2"   # solo lunes y miércoles
        self.main.checar_reloj_bot(ahora=mx(27, 8, 15))        # martes
        self.assertEqual(self.enviados, [])
        self.main.checar_reloj_bot(ahora=mx(26, 8, 15))        # lunes
        self.assertEqual(len(self.enviados), 1)

    def test_el_cierre_automatico_sigue_corriendo_en_domingo(self):
        BD.tablas.setdefault("registros_asistencia", []).append(
            {"empleado_id": "EMP-1", "tipo_registro": "ENTRADA", "fecha_hora": mx(25, 8).isoformat()})
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(25, 19)), ["EMP-1"])


class CierreAutomaticoTest(BaseTest):
    def entrada(self, emp_id, cuando):
        BD.filas("registros_asistencia")
        BD.tablas.setdefault("registros_asistencia", []).append(
            {"empleado_id": emp_id, "tipo_registro": "ENTRADA", "fecha_hora": cuando.isoformat()})

    def salida(self, emp_id, cuando):
        BD.tablas.setdefault("registros_asistencia", []).append(
            {"empleado_id": emp_id, "tipo_registro": "SALIDA", "fecha_hora": cuando.isoformat()})

    def test_cierra_a_la_hora_de_corte_con_metodo_auto(self):
        self.entrada("EMP-1", mx(24, 8))
        BD.tablas["estados_conversacion"] = [{"telefono": TEL["EMP-1"], "estado": "EN_TURNO", "datos_temporales": {}}]
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 18, 1)), ["EMP-1"])
        salida = self.registros("SALIDA")[0]
        self.assertEqual((salida["empleado_id"], salida["metodo"], salida["fecha_hora"]),
                         ("EMP-1", "AUTO", mx(24, 18).isoformat()))
        self.assertNotIn("foto_url", salida)
        self.assertIsNone(self.estado("EMP-1"))   # mañana le sale "1 Entrada"

    def test_antes_de_la_hora_de_corte_no_cierra(self):
        self.entrada("EMP-1", mx(24, 8))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 17, 59)), [])
        self.assertEqual(self.registros("SALIDA"), [])

    def test_no_cierra_a_quien_ya_registro_su_salida(self):
        self.entrada("EMP-1", mx(24, 8))
        self.salida("EMP-1", mx(24, 17, 30))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 19)), [])
        self.assertEqual(len(self.registros("SALIDA")), 1)

    def test_correrlo_dos_veces_no_duplica_la_salida(self):
        self.entrada("EMP-1", mx(24, 8))
        self.main.cerrar_turnos_abiertos(ahora=mx(24, 18, 1))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 18, 2)), [])
        self.assertEqual(len(self.registros("SALIDA")), 1)

    def test_si_se_perdio_el_cierre_de_ayer_se_hace_a_la_hora_de_corte_de_ayer(self):
        self.entrada("EMP-1", mx(23, 8))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 9)), ["EMP-1"])
        self.assertEqual(self.registros("SALIDA")[0]["fecha_hora"], mx(23, 18).isoformat())

    def test_una_entrada_despues_de_la_hora_de_corte_no_se_toca(self):
        self.entrada("EMP-1", mx(24, 19))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 23)), [])

    def test_dry_run_no_escribe_nada(self):
        self.entrada("EMP-1", mx(24, 8))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 19), dry_run=True), ["EMP-1"])
        self.assertEqual(self.registros("SALIDA"), [])

    def test_solo_empleados_limita_el_cierre(self):
        self.entrada("EMP-1", mx(24, 8))
        self.entrada("EMP-2", mx(24, 8))
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 19), solo_empleados=["EMP-2"]), ["EMP-2"])
        self.assertEqual([r["empleado_id"] for r in self.registros("SALIDA")], ["EMP-2"])

    def test_sin_hora_de_corte_configurada_no_cierra_nada(self):
        self.entrada("EMP-1", mx(24, 8))
        BD.tablas["configuracion"] = [{"id": 1, "hora_corte_salida": None}]
        self.assertEqual(self.main.cerrar_turnos_abiertos(ahora=mx(24, 19)), [])

    def test_con_muchos_registros_lee_todas_las_paginas(self):
        self.main.TAMANO_PAGINA_CIERRE = 2
        try:
            self.entrada("EMP-1", mx(24, 8))
            self.salida("EMP-1", mx(24, 17))
            self.entrada("EMP-2", mx(24, 8, 5))
            self.entrada("EMP-3", mx(24, 8, 10))
            self.assertEqual(sorted(self.main.cerrar_turnos_abiertos(ahora=mx(24, 19))), ["EMP-2", "EMP-3"])
        finally:
            self.main.TAMANO_PAGINA_CIERRE = 1000

    def test_el_job_respeta_el_boton_de_suspender(self):
        self.entrada("EMP-1", mx(24, 8))
        self.main.bot_esta_activo = lambda: False
        try:
            self.main.checar_cierre_automatico()
        finally:
            self.main.bot_esta_activo = lambda: True
        self.assertEqual(self.registros("SALIDA"), [])


if __name__ == "__main__":
    unittest.main()
