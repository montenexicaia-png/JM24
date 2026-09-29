"""
Prueba rápida y aislada de la conexión con Bot Matrix Panel.
No manda nada a WhatsApp ni toca datos de la obra. Solo verifica que:
  1. Las variables PANEL_SUPABASE_URL / PANEL_SUPABASE_KEY / PANEL_BOT_ID estén bien puestas.
  2. bot_esta_activo() lee correctamente el estado desde bots_instancias.
  3. registrar_consumo_mensaje() sí suma en consumo_diario.

Uso: python test_panel_connection.py
"""

import database

print("=" * 50)
print("PRUEBA DE CONEXIÓN A BOT MATRIX PANEL")
print("=" * 50)

if not database.PANEL_SUPABASE_URL or not database.PANEL_SUPABASE_KEY:
    print("❌ Falta PANEL_SUPABASE_URL o PANEL_SUPABASE_KEY en tu .env")
    raise SystemExit(1)

if not database.PANEL_BOT_ID:
    print("❌ Falta PANEL_BOT_ID en tu .env (crea la instancia de bot en el panel primero)")
    raise SystemExit(1)

if not database.supabase_panel:
    print("❌ No se pudo crear el cliente de Supabase del Panel (revisa la URL/KEY)")
    raise SystemExit(1)

print(f"✅ Conectado. PANEL_BOT_ID = {database.PANEL_BOT_ID}\n")

activo = database.bot_esta_activo()
print(f"🔎 Estado leído desde el Panel: {'ACTIVO' if activo else 'SUSPENDIDO'}")
print("   (Cámbialo en Bots & Consumo → drawer del cliente → switch, y vuelve a correr este script)\n")

print("📝 Registrando un mensaje de prueba en consumo_diario...")
database.registrar_consumo_mensaje()

hoy = __import__("datetime").date.today().isoformat()
resp = (
    database.supabase_panel.table("consumo_diario")
    .select("*")
    .eq("bot_id", database.PANEL_BOT_ID)
    .eq("fecha", hoy)
    .eq("proveedor", "meta_mensajes")
    .execute()
)

if resp.data:
    print(f"✅ Fila en consumo_diario para hoy: {resp.data[0]}")
    print("\nVuelve a correr este script otra vez: 'cantidad' debe subir en +1 cada vez.")
else:
    print("❌ No se encontró la fila esperada en consumo_diario. Revisa el error de arriba (si hubo).")

print("=" * 50)
