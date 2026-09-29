import os
import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# 1. Cargar las variables ocultas del archivo .env
load_dotenv()

# 2. Obtener las credenciales de Supabase de forma segura
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

if not url or not key:
    raise ValueError("¡Faltan las credenciales de Supabase en el archivo .env!")

# 3. Inicializar el cliente (el puente entre tu bot y la base de datos)
supabase: Client = create_client(url, key)

# ==========================================
# 🎛️ CONEXIÓN A BOT MATRIX PANEL (monitoreo)
# ==========================================
# Proyecto de Supabase DISTINTO al de arriba (`supabase`). Se usa ÚNICAMENTE para:
#   - leer si este bot está activo/suspendido (bots_instancias)
#   - registrar consumo de mensajes (consumo_diario)
# Nunca se toca aquí ningún dato operativo de la obra (empleados, asistencias, etc.).
PANEL_SUPABASE_URL = os.getenv("PANEL_SUPABASE_URL")
PANEL_SUPABASE_KEY = os.getenv("PANEL_SUPABASE_KEY")
PANEL_BOT_ID = os.getenv("PANEL_BOT_ID")

supabase_panel: Client | None = None
if PANEL_SUPABASE_URL and PANEL_SUPABASE_KEY:
    try:
        supabase_panel = create_client(PANEL_SUPABASE_URL, PANEL_SUPABASE_KEY)
    except Exception as e:
        print(f"⚠️ No se pudo conectar al Supabase del Panel: {e}")
else:
    print("⚠️ PANEL_SUPABASE_URL/PANEL_SUPABASE_KEY no configuradas. Monitoreo del Panel desactivado (el bot sigue funcionando normal).")


def bot_esta_activo() -> bool:
    """
    Consulta en el Panel si este bot está suspendido.
    Si el Panel no está configurado o falla la consulta, se asume ACTIVO (fail-open):
    un problema de monitoreo nunca debe impedir que los trabajadores registren su asistencia.
    """
    if not supabase_panel or not PANEL_BOT_ID:
        return True
    try:
        resp = supabase_panel.table("bots_instancias").select("estado").eq("id", PANEL_BOT_ID).limit(1).execute()
        if resp.data:
            return resp.data[0].get("estado") == "activo"
        return True
    except Exception as e:
        print(f"⚠️ No se pudo verificar el estado del bot en el Panel: {e}")
        return True


def registrar_consumo_mensaje():
    """
    Suma 1 al contador de mensajes de hoy en consumo_diario (proveedor='meta').
    Nunca lanza una excepción hacia afuera: si falla, solo se pierde ese registro de consumo,
    jamás debe tumbar el flujo real del bot.
    """
    if not supabase_panel or not PANEL_BOT_ID:
        return
    try:
        hoy = datetime.date.today().isoformat()
        existente = (
            supabase_panel.table("consumo_diario")
            .select("id, cantidad")
            .eq("bot_id", PANEL_BOT_ID)
            .eq("fecha", hoy)
            .eq("proveedor", "meta_mensajes")
            .limit(1)
            .execute()
        )

        if existente.data:
            fila = existente.data[0]
            nueva_cantidad = (fila.get("cantidad") or 0) + 1
            supabase_panel.table("consumo_diario").update({"cantidad": nueva_cantidad}).eq(
                "id", fila["id"]
            ).execute()
        else:
            supabase_panel.table("consumo_diario").insert(
                {
                    "bot_id": PANEL_BOT_ID,
                    "fecha": hoy,
                    "proveedor": "meta_mensajes",
                    "cantidad": 1,
                }
            ).execute()
    except Exception as e:
        print(f"⚠️ No se pudo registrar el consumo en el Panel: {e}")

def probar_conexion():
    """Función rápida para verificar que el puente funciona"""
    try:
        # Hacemos una llamada muy básica a la API para ver si responde
        respuesta = supabase.table("empleados").select("*").limit(1).execute()
        print("✅ ¡Conexión exitosa a Supabase!")
        return True
    except Exception as e:
        # Si la tabla no existe, dará un error, pero el error confirmará que conectamos
        if "relation \"public.empleados\" does not exist" in str(e):
             print("✅ ¡Conexión exitosa a Supabase! (Falta crear las tablas, pero ya entramos)")
             return True
        else:
             print(f"❌ Error de conexión: {e}")
             return False

# Este bloque solo se ejecuta si corres este archivo directamente
if __name__ == "__main__":
    probar_conexion()