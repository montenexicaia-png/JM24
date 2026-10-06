"""
Aviso de "datos faltantes" para trabajadores cargados sin su información completa
(por ejemplo desde una lista de Excel con solo nombre y teléfono).

Lo comparten el panel (botón en Gestión RH), el comando por WhatsApp y el recordatorio
automático. NO importa `main` a propósito: importarlo arranca el scheduler y puede
disparar mensajes reales. Por eso tiene su propio envío por Meta.
"""
import os
import re
import datetime
import requests
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from database import supabase, registrar_consumo_mensaje
from datos_empleado import ESTADO_INCOMPLETO, datos_faltantes

load_dotenv()

MIN_HORAS_ENTRE_AVISOS = 24      # tope anti-spam: no reenviar antes de este tiempo (salvo forzar=True)

# Plantilla aprobada en Meta (categoría Utilidad, es_MX, 1 variable en el cuerpo: el nombre de pila)
PLANTILLA_DATOS_FALTANTES = os.getenv("PLANTILLA_DATOS_FALTANTES", "completar_datos_registro")


def ahora_mexico() -> datetime.datetime:
    """Fecha y hora actual en la zona horaria de Ciudad de México."""
    return datetime.datetime.now(ZoneInfo("America/Mexico_City"))


def horas_desde_ultimo_aviso(empleado: dict) -> float | None:
    """Horas transcurridas desde el último aviso de datos faltantes, o None si nunca se le mandó."""
    registro = (empleado.get("datos_adicionales") or {}).get("aviso_datos") or {}
    ultimo = registro.get("ultimo_envio")
    if not ultimo:
        return None
    try:
        return (ahora_mexico() - datetime.datetime.fromisoformat(ultimo)).total_seconds() / 3600
    except ValueError:
        return None


def _enviar_plantilla(telefono: str, nombre_plantilla: str, variable_texto: str) -> bool:
    """Manda una plantilla de Meta con 1 variable en el cuerpo. True solo si Meta la aceptó."""
    TOKEN = os.getenv("TOKEN_ACCESO_META", "").strip().strip('"').strip("'")
    PHONE_ID = os.getenv("PHONE_NUMBER_ID", "").strip().strip('"').strip("'")

    if not TOKEN or not PHONE_ID:
        print("❌ Error: No se encontraron las credenciales de Meta.")
        return False

    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono.strip().lstrip("+"),
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {"code": "es_MX"},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": variable_texto}]}
            ]
        }
    }

    try:
        respuesta = requests.post(url, headers=headers, json=payload, timeout=20)
        if respuesta.status_code in (200, 201):
            print(f"✅ Plantilla '{nombre_plantilla}' enviada a {payload['to']}")
            return True
        print(f"⚠️ Error de Meta al enviar plantilla a {payload['to']}: {respuesta.text}")
    except Exception as e:
        print(f"❌ Error de conexión al enviar plantilla: {e}")
    return False


def _registrar_aviso(empleado: dict) -> None:
    """Guarda en `datos_adicionales` cuándo se avisó y cuántas veces, sin pisar otras llaves."""
    datos = dict(empleado.get("datos_adicionales") or {})
    previo = datos.get("aviso_datos") or {}
    datos["aviso_datos"] = {
        "ultimo_envio": ahora_mexico().isoformat(),
        "avisos_enviados": previo.get("avisos_enviados", 0) + 1,
    }
    try:
        supabase.table("empleados").update({"datos_adicionales": datos}) \
            .eq("empleado_id", empleado["empleado_id"]).execute()
    except Exception as e:
        print(f"⚠️ El aviso salió, pero no se pudo registrar en datos_adicionales: {e}")


def enviar_aviso_datos_faltantes(empleado: dict, forzar: bool = False) -> tuple[bool, str]:
    """
    Manda la plantilla de "completa tus datos" a un empleado INCOMPLETO.
    Devuelve (enviado, motivo) para que el panel o el comando muestren por qué no se envió.
    `forzar=True` se salta solo el tope de MIN_HORAS_ENTRE_AVISOS; el resto de validaciones siempre aplica.
    """
    nombre = (empleado.get("nombre_completo") or "").strip()
    telefono = (empleado.get("telefono") or "").strip()

    if empleado.get("estado") != ESTADO_INCOMPLETO:
        return False, f"{nombre or empleado.get('empleado_id')} no está en estado {ESTADO_INCOMPLETO}"
    if not datos_faltantes(empleado):
        return False, f"{nombre} ya tiene todos sus datos"
    if not telefono:
        return False, f"{nombre} no tiene teléfono registrado"
    if not re.fullmatch(r"\+\d{11,15}", telefono):
        return False, f"{nombre} tiene un teléfono con formato inválido"

    horas = horas_desde_ultimo_aviso(empleado)
    if not forzar and horas is not None and horas < MIN_HORAS_ENTRE_AVISOS:
        return False, f"{nombre} ya recibió un aviso hace {horas:.0f} h"

    primer_nombre = nombre.split()[0].title() if nombre else "trabajador"
    if not _enviar_plantilla(telefono, PLANTILLA_DATOS_FALTANTES, primer_nombre):
        return False, f"Meta no aceptó el mensaje para {nombre}"

    registrar_consumo_mensaje()
    _registrar_aviso(empleado)
    return True, f"Aviso enviado a {nombre}"
