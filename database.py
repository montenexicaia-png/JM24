import os
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