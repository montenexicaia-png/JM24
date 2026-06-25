from database import supabase

# --- FUNCIONES DE MEMORIA (MÁQUINA DE ESTADOS) ---
def obtener_estado(telefono: str):
    resultado = supabase.table("estados_conversacion").select("*").eq("telefono", telefono).execute()
    if resultado.data:
        return resultado.data[0]
    return None

def guardar_estado(telefono: str, estado: str, datos_temporales: dict = None):
    if datos_temporales is None:
        datos_temporales = {}
    supabase.table("estados_conversacion").upsert({
        "telefono": telefono,
        "estado": estado,
        "datos_temporales": datos_temporales
    }).execute()

def limpiar_estado(telefono: str):
    supabase.table("estados_conversacion").delete().eq("telefono", telefono).execute()

# --- CEREBRO PRINCIPAL ---
def procesar_mensaje_whatsapp(telefono: str, texto_recibido: str) -> str:
    texto = texto_recibido.strip().upper()
    
    try:
        res_empleado = supabase.table("empleados").select("*").eq("telefono", telefono).execute()
        if not res_empleado.data:
            return "❌ Tu número no está registrado. Por favor, contacta al administrador."
        empleado = res_empleado.data[0]
    except Exception as e:
        return f"⚠️ Error de conexión: {str(e)}"

    memoria = obtener_estado(telefono)
    estado_actual = memoria["estado"] if memoria else None
    datos_temp = memoria["datos_temporales"] if memoria else {}

    # === FLUJO DE ENTRADA ===
    # Si manda "1", "2", "3" o "4", entramos a los flujos. Si manda un simple "Hola", cae al 'else' y le mostramos el menú.

    if estado_actual is None:
        if texto == "1":
            guardar_estado(telefono, "ESPERANDO_UBICACION", {"empleado_id": empleado['empleado_id']})
            return f"¡Excelente inicio de jornada, {empleado['nombre_completo']}! 🏗️ Compárteme tu 📍 *Ubicación actual*."
        else:
            # Menú de inicio
            return (f"🤖 Hola, {empleado['nombre_completo']}. Selecciona una opción enviando el *NÚMERO*:\n\n"
                    f"1️⃣ 🟢 Registrar ENTRADA")

    # 2. FLUJO DURANTE LA JORNADA (AVISOS, URGENCIA Y SALIDA)
    elif estado_actual == "EN_TURNO":
        if texto == "2":
            guardar_estado(telefono, "ESPERANDO_AVISO", {"empleado_id": empleado['empleado_id']})
            return "🟡 *MODO AVISO* \nEntendido. Escribe brevemente cuál es el reporte o novedad de la obra:"
        
        elif texto == "3":
            guardar_estado(telefono, "ESPERANDO_URGENCIA", {"empleado_id": empleado['empleado_id']})
            return "🔴 *MODO URGENCIA* \nDescribe el problema. (Se notificará de inmediato al contratista):"
        
        elif texto == "4":
            guardar_estado(telefono, "ESPERANDO_UBICACION_SALIDA", {"empleado_id": empleado['empleado_id']})
            return "🏁 *INICIANDO SALIDA* \n¡Buen trabajo hoy! Para cerrar tu turno, compárteme tu 📍 *Ubicación actual*."
        
        else:
            # Si manda cualquier otra cosa mientras está en turno, le mostramos sus opciones
            return (f"🤖 Estás en turno, {empleado['nombre_completo']}. ¿Qué deseas hacer? (Envía el *NÚMERO*):\n\n"
                    f"2️⃣ 🟡 Enviar un AVISO (Reporte normal)\n"
                    f"3️⃣ 🔴 Reportar URGENCIA (Crítico)\n"
                    f"4️⃣ 🏁 Registrar SALIDA")

    elif estado_actual == "ESPERANDO_UBICACION":
        if "," in texto_recibido:
            # Separamos la latitud y longitud por la coma
            partes = texto_recibido.split(",")
            datos_temp["latitud"] = partes[0].strip()
            datos_temp["longitud"] = partes[1].strip()
            
            guardar_estado(telefono, "ESPERANDO_FOTO_ENTRADA", datos_temp)
            return "✅ Ubicación recibida. Envíame una 📸 *Foto* de tu frente de trabajo para iniciar."
        else:
            return "⚠️ Por favor, usa el clip de WhatsApp 📎 para enviar tu 📍 *Ubicación actual*."

    elif estado_actual == "ESPERANDO_FOTO_ENTRADA":
        if texto_recibido.startswith("FOTO|"):
            # Extraemos la URL real que viene después del símbolo |
            url_real = texto_recibido.split("|")[1]
            try:
                # --- NUEVO: Armamos el enlace de Google Maps ---
                lat = datos_temp.get("latitud")
                lon = datos_temp.get("longitud")
                enlace_mapas = f"https://www.google.com/maps?q={lat},{lon}"
                
                supabase.table("registros_asistencia").insert({
                    "empleado_id": empleado['empleado_id'],
                    "tipo_registro": "ENTRADA",
                    "latitud": lat,
                    "longitud": lon,
                    "ubicacion": enlace_mapas,  # <-- AQUÍ NACE LA MAGIA QUE LEE EL PANEL WEB
                    "foto_url": url_real
                }).execute()
                guardar_estado(telefono, "EN_TURNO", {"empleado_id": empleado['empleado_id']})
                return f"✅ ¡Tu ENTRADA quedó registrada oficialmente, {empleado['nombre_completo']}! Ya estás en turno."
            except Exception as e:
                return f"❌ Error: {str(e)}"
        else:
            return "⚠️ Por favor, usa la cámara de WhatsApp 📷 para enviar la *Foto*."

    # === FLUJO DE AVISOS (REPORTE NORMAL) ===
    elif estado_actual == "ESPERANDO_AVISO":
        try:
            supabase.table("reportes_incidentes").insert({
                "empleado_id": empleado['empleado_id'],
                "descripcion": texto_recibido.strip(), # Guardamos tal cual lo que escribió
                "estado": "AVISO"
            }).execute()
            
            # Lo regresamos a su turno normal para que pueda seguir usando el menú
            guardar_estado(telefono, "EN_TURNO", {"empleado_id": empleado['empleado_id']})
            return "✅ *Aviso registrado.* Quedó guardado en la bitácora del día. Sigues en turno."
        except Exception as e:
            return f"❌ Error al guardar el aviso: {str(e)}"

    # === FLUJO DE URGENCIAS (CRÍTICO) ===
    elif estado_actual == "ESPERANDO_URGENCIA":
        try:
            supabase.table("reportes_incidentes").insert({
                "empleado_id": empleado['empleado_id'],
                "descripcion": texto_recibido.strip(),
                "estado": "URGENTE" # Marcado como crítico para destacar en base de datos
            }).execute()
            
            # Aquí en el futuro puedes agregar el código para enviarle un WhatsApp directo al contratista
            
            guardar_estado(telefono, "EN_TURNO", {"empleado_id": empleado['empleado_id']})
            return "🚨 *REPORTE URGENTE ENVIADO* \nSe ha notificado inmediatamente. Sigues en turno."
        except Exception as e:
            return f"❌ Error al reportar la urgencia: {str(e)}"    

    # === FLUJO DE SALIDA (CIERRE DE TURNO) ===
    elif estado_actual == "ESPERANDO_UBICACION_SALIDA":
        if "," in texto_recibido:
            partes = texto_recibido.split(",")
            datos_temp["latitud_salida"] = partes[0].strip()
            datos_temp["longitud_salida"] = partes[1].strip()
            
            guardar_estado(telefono, "ESPERANDO_FOTO_SALIDA", datos_temp)
            return "✅ Ubicación de salida recibida. Por favor, envíame una 📸 *Foto* del avance del día."
        else:
            return "⚠️ Por favor, usa el clip de WhatsApp 📎 para enviar tu 📍 *Ubicación actual*."

    elif estado_actual == "ESPERANDO_FOTO_SALIDA":
        if texto_recibido.startswith("FOTO|"):
            datos_temp["url_foto_salida"] = texto_recibido.split("|")[1]
            guardar_estado(telefono, "ESPERANDO_AVANCES", datos_temp)
            return "📸 Foto guardada. Ahora descríbeme brevemente:\n\n*¿Qué avances lograste el día de hoy?*"
        else:
            return "⚠️ Por favor, usa la cámara de WhatsApp 📷 para enviar la *Foto*."

    elif estado_actual == "ESPERANDO_AVANCES":
        datos_temp["avances"] = texto_recibido.strip()
        guardar_estado(telefono, "ESPERANDO_PENDIENTES", datos_temp)
        return "📝 Avance registrado. Por último:\n\n*¿Qué tareas quedan PENDIENTES para mañana?*"

    elif estado_actual == "ESPERANDO_PENDIENTES":
        try:
            # --- NUEVO: Armamos el enlace de Google Maps para la salida ---
            lat_salida = datos_temp.get("latitud_salida")
            lon_salida = datos_temp.get("longitud_salida")
            enlace_mapas = f"https://www.google.com/maps?q={lat_salida},{lon_salida}"
            
            supabase.table("registros_asistencia").insert({
                "empleado_id": empleado['empleado_id'],
                "tipo_registro": "SALIDA",
                "latitud": lat_salida,
                "longitud": lon_salida,
                "ubicacion": enlace_mapas,  # <-- AQUÍ NACE LA MAGIA QUE LEE EL PANEL WEB
                "foto_url": datos_temp.get("url_foto_salida"),
                "avances": datos_temp.get("avances"),
                "pendientes": texto_recibido.strip()
            }).execute()
            
            # Turno terminado, limpiamos la memoria para que mañana empiece de cero
            limpiar_estado(telefono)
            return "🌙 ¡Bitácora completada y enviada al contratista! Tu SALIDA oficial ha sido registrada. ¡Buen descanso!"
        except Exception as e:
            return f"❌ Error al guardar tu salida: {str(e)}"   

    # === MENSAJE POR DEFECTO (CUANDO EL BOT ESPERA FOTOS O UBICACIONES) ===
    else:
        return f"🤖 {empleado['nombre_completo']}, por favor responde a la instrucción anterior enviando lo solicitado."


# --- SIMULADOR DE PRUEBAS ---
if __name__ == "__main__":
    telefono_prueba = "+525512345678"
    
    print("==============================================")
    print("🚀 PROBANDO FLUJO COMPLETO EN CONSOLA 🚀")
    print("==============================================\n")
    
    print("👨‍🔧 Trabajador: 'Hola'")
    print(f"🤖 Bot: {procesar_mensaje_whatsapp(telefono_prueba, 'Hola')}\n")
    
    print("👨‍🔧 Trabajador: '1'")
    print(f"🤖 Bot: {procesar_mensaje_whatsapp(telefono_prueba, '1')}\n")