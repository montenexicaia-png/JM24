from database import supabase
import random
import datetime
from zoneinfo import ZoneInfo

def hora_mexico():
    """Devuelve la fecha y hora actual, siempre en la zona horaria de Ciudad de México"""
    return datetime.datetime.now(ZoneInfo("America/Mexico_City")).isoformat()

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

def obtener_roles_dinamicos():
    """Lee la base de datos y extrae la lista oficial de puestos desde el catálogo."""
    try:
        # Ahora consultamos directo a la tabla oficial que creamos
        resultado = supabase.table("catalogo_puestos").select("nombre").order("id").execute()
        if resultado.data:
            # Extraemos los nombres
            roles = [item["nombre"] for item in resultado.data if item.get("nombre")]
            if roles:
                return roles
    except Exception as e:
        pass
    
    # Fallback de seguridad en caso de que se caiga el internet o la base de datos
    return ["Técnico", "Ayudante"]

# --- CEREBRO PRINCIPAL ---
def procesar_mensaje_whatsapp(telefono: str, texto_recibido: str) -> str:
    texto = texto_recibido.strip().upper()
    
    # 1. LEEMOS LA MEMORIA PRIMERO (Para saber si ya estábamos platicando)
    memoria = obtener_estado(telefono)
    estado_actual = memoria["estado"] if memoria else None
    datos_temp = memoria["datos_temporales"] if memoria else {}

    # 2. BUSCAMOS AL EMPLEADO EN LA BD
    empleado = None
    try:
        res_empleado = supabase.table("empleados").select("*").eq("telefono", telefono).execute()
        
        if res_empleado.data:
            # === EL EMPLEADO SÍ EXISTE ===
            empleado = res_empleado.data[0]
            
            # Filtros de seguridad
            if empleado["estado"] == "PENDIENTE":
                return "⏳ Hola. Tu cuenta está actualmente *En Revisión* en la Sala de Espera. Por favor, espera a que el administrador apruebe tu acceso."
            elif empleado["estado"] == "INACTIVO":
                return "⛔ Tu perfil se encuentra inactivo. Por favor, comunícate con Recursos Humanos."
        else:
            # === EL EMPLEADO NO EXISTE ===
            # Si NO existe, y tampoco estaba en proceso de registro, leemos el Interruptor
            if not estado_actual or not estado_actual.startswith("ONBOARDING"):
                res_config = supabase.table("configuracion").select("registro_abierto").eq("id", 1).execute()
                registro_abierto = res_config.data[0]["registro_abierto"] if res_config.data else False
                
                if not registro_abierto:
                    return ("👋 ¡Hola! Te has comunicado al asistente virtual de la Obra. 🏗️\n\n"
                            "De momento nuestro reclutamiento está cerrado y tu número no está en nuestra lista de personal.\n\n"
                            "Si eres cliente o proveedor, por favor deja tu mensaje y un asesor humano se pondrá en contacto contigo pronto. ¡Excelente día!")
                else:
                    guardar_estado(telefono, "ONBOARDING_NOMBRE", {})
                    return ("👋 ¡Bienvenido al sistema de registro de Obra! 🏗️\n\n"
                            "Vamos a crear tu perfil. Para empezar, por favor escribe tu *Nombre Completo*:")
    except Exception as e:
        return f"⚠️ Error de conexión: {str(e)}"

    # 3. MÁQUINA DE ESTADOS (EL FLUJO DE CONVERSACIÓN)

    # === FLUJO DE ONBOARDING (NUEVO REGISTRO) ===
    if estado_actual == "ONBOARDING_NOMBRE":
        # 1. Guardar y formatear el nombre (Ej. "juan lopez" -> "Juan Lopez")
        nombre_formateado = texto_recibido.strip().title()
        datos_temp["nombre"] = nombre_formateado
        
        # 2. Obtener roles de la base de datos
        roles_disponibles = obtener_roles_dinamicos()
        
        # 3. Crear el menú numérico
        mensaje_roles = f"¡Gusto en saludarte, {nombre_formateado}! 🤝\n\nPara asignar tu puesto, responde con el *NÚMERO* correspondiente:\n\n"
        mapeo_roles = {}
        
        for i, rol in enumerate(roles_disponibles, start=1):
            mensaje_roles += f"{i}️⃣ {rol}\n"
            mapeo_roles[str(i)] = rol 
            
        datos_temp["mapeo_roles"] = mapeo_roles
        
        guardar_estado(telefono, "ONBOARDING_PUESTO", datos_temp)
        return mensaje_roles

    elif estado_actual == "ONBOARDING_PUESTO":
        # 1. Validamos qué número escribió el usuario
        opcion_elegida = texto_recibido.strip()
        
        # 2. Recuperamos el diccionario que guardamos en el paso anterior
        mapeo_roles = datos_temp.get("mapeo_roles", {})
        
        if opcion_elegida in mapeo_roles:
            # ¡Eligió una opción válida! Extraemos el texto del puesto
            rol_seleccionado = mapeo_roles[opcion_elegida]
            datos_temp["rol"] = rol_seleccionado
            
            # --- NUEVO: Avanzamos a pedir el Rango ---
            guardar_estado(telefono, "ONBOARDING_RANGO", datos_temp)
            
            return (f"✅ Puesto guardado como *{rol_seleccionado}*.\n\n"
                    f"🎖️ Ahora selecciona tu *Rango* respondiendo con el NÚMERO correspondiente:\n\n"
                    f"1️⃣ Cabo\n"
                    f"2️⃣ Oficial\n"
                    f"3️⃣ Medio\n"
                    f"4️⃣ Ayudante")
        else:
            # Si escribe algo que no es un número del menú
            return "⚠️ Opción no válida. Por favor, responde únicamente con el *NÚMERO* de la lista."

    # ==========================================
    # ESTADO: PIDIENDO EL RANGO
    # ==========================================
    elif estado_actual == "ONBOARDING_RANGO":
        opcion_elegida = texto_recibido.strip()
        rangos_disponibles = {"1": "Cabo", "2": "Oficial", "3": "Medio", "4": "Ayudante"}
        
        if opcion_elegida in rangos_disponibles:
            rango_seleccionado = rangos_disponibles[opcion_elegida]
            datos_temp["rango"] = rango_seleccionado
            
            # --- NUEVO: Consultamos las obras ACTIVAS para el siguiente paso ---
            try:
                res_obras = supabase.table("catalogo_obras").select("nombre").eq("estado", "ACTIVA").execute()
                obras_activas = [o["nombre"] for o in res_obras.data] if res_obras.data else []
            except:
                obras_activas = []
                
            if not obras_activas:
                # Si por alguna razón no hay obras registradas, nos saltamos este paso y vamos directo a la foto
                datos_temp["obra"] = "Sin Obra"
                guardar_estado(telefono, "ONBOARDING_FOTO", datos_temp)
                return (f"✅ Rango guardado como *{rango_seleccionado}*.\n\n"
                        f"Por último, envíame una 📸 *Foto de perfil* tuya "
                        f"(tipo credencial o selfie) para terminar tu registro.")

            # Si sí hay obras, armamos el menú dinámico
            mensaje_obras = f"✅ Rango guardado como *{rango_seleccionado}*.\n\n🏗️ ¿A qué obra fuiste asignado? (Responde con el *NÚMERO*):\n\n"
            mapeo_obras = {}
            
            for i, obra in enumerate(obras_activas, start=1):
                mensaje_obras += f"{i}️⃣ {obra}\n"
                mapeo_obras[str(i)] = obra
                
            datos_temp["mapeo_obras"] = mapeo_obras
            
            # Avanzamos al nuevo estado
            guardar_estado(telefono, "ONBOARDING_OBRA", datos_temp)
            return mensaje_obras
        else:
            return "⚠️ Opción no válida. Por favor, responde con un NÚMERO del 1 al 4."

    # ==========================================
    # NUEVO ESTADO: ASIGNACIÓN DE OBRA
    # ==========================================
    elif estado_actual == "ONBOARDING_OBRA":
        opcion_elegida = texto_recibido.strip()
        mapeo_obras = datos_temp.get("mapeo_obras", {})
        
        if opcion_elegida in mapeo_obras:
            obra_seleccionada = mapeo_obras[opcion_elegida]
            datos_temp["obra"] = obra_seleccionada
            
            # Ahora sí, avanzamos a pedir la foto
            guardar_estado(telefono, "ONBOARDING_FOTO", datos_temp)
            return (f"✅ Obra guardada como *{obra_seleccionada}*.\n\n"
                    f"Por último, envíame una 📸 *Foto de perfil* tuya "
                    f"(tipo credencial o selfie) para terminar tu registro.")
        else:
            return "⚠️ Opción no válida. Por favor, responde únicamente con el *NÚMERO* de la lista."

    elif estado_actual == "ONBOARDING_FOTO":
        # Validamos que el mensaje realmente sea una imagen enviada por WhatsApp
        if texto_recibido.startswith("FOTO|"):
            # Extraemos la URL que viene después del símbolo |
            url_foto_temp = texto_recibido.split("|")[1]
            datos_temp["foto_url_temp"] = url_foto_temp
            
            # Avanzamos al paso de confirmación
            guardar_estado(telefono, "ONBOARDING_CONFIRMACION", datos_temp)
            
            # Construimos el resumen para el trabajador (AHORA INCLUYE OBRA)
            nombre = datos_temp.get("nombre", "Desconocido")
            rol = datos_temp.get("rol", "Desconocido")
            rango = datos_temp.get("rango", "Desconocido")
            obra = datos_temp.get("obra", "Sin Obra") # <-- EXTRAEMOS LA OBRA
            
            return (f"📝 Por favor revisa que tus datos sean correctos:\n\n"
                    f"👤 *Nombre:* {nombre}\n"
                    f"👷‍♂️ *Puesto:* {rol}\n"
                    f"🎖️ *Rango:* {rango}\n"
                    f"🏗️ *Obra:* {obra}\n" # <-- LA MOSTRAMOS EN EL RESUMEN
                    f"📸 *Foto:* ✅ Recibida\n\n"
                    f"¿Todo está bien? (Responde con el NÚMERO):\n"
                    f"1️⃣ Sí, enviar solicitud\n"
                    f"2️⃣ No, empezar de nuevo")
        else:
            return "⚠️ Por favor, usa la cámara o galería de WhatsApp 📷 para enviar tu *Foto de perfil*."

    # Aquí atraparemos la confirmación final para guardar en la BD
    elif estado_actual == "ONBOARDING_CONFIRMACION":
        opcion = texto_recibido.strip()
        
        if opcion == "1":
            try:
                import random
                # 1. Generamos un ID único para el trabajador (Ej. EMP-4829)
                nuevo_id = f"EMP-{random.randint(1000, 9999)}"
                
                # 2. Inyectamos toda la información a Supabase
                supabase.table("empleados").insert({
                    "empleado_id": nuevo_id,
                    "nombre_completo": datos_temp.get("nombre"),
                    "telefono": telefono,
                    "rol": datos_temp.get("rol"),
                    "rango": datos_temp.get("rango"),
                    "obra_actual": datos_temp.get("obra", "Sin Obra"),  # <-- NUEVO: AQUÍ GUARDAMOS LA OBRA
                    "foto_perfil_url": datos_temp.get("foto_url_temp"),
                    "estado": "PENDIENTE"
                }).execute()
                
                # 3. Limpiamos la memoria porque el registro terminó exitosamente
                limpiar_estado(telefono)
                
                return ("✅ *¡Solicitud enviada con éxito!*\n\n"
                        "Tu perfil ha sido guardado y enviado a la ⏳ *Sala de Espera*.\n"
                        "Por favor, espera a que el administrador apruebe tu acceso. Te avisaremos cuando puedas comenzar a registrar tus asistencias.")
            
            except Exception as e:
                return f"❌ Hubo un error al procesar tu registro: {str(e)}"
                
        elif opcion == "2":
            # Si se equivocó y quiere empezar de nuevo, borramos los datos temporales y lo regresamos al paso 1
            guardar_estado(telefono, "ONBOARDING_NOMBRE", {})
            return "🔄 Reiniciando registro...\n\nPor favor, escribe nuevamente tu *Nombre Completo*:"
            
        else:
            return "⚠️ Opción no válida. Responde con *1* (Sí, enviar) o *2* (No, empezar de nuevo)."

    # === FLUJOS NORMALES (ENTRADAS, SALIDAS, REPORTES) ===
    # A partir de aquí, el código original requiere que el empleado ya exista formalmente.
    if not empleado:
        return "❌ Ocurrió un error. No tienes un perfil activo."

    if estado_actual is None: # <-- AQUÍ VUELVE A EMPEZAR TU CÓDIGO ORIGINAL
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
                    "fecha_hora": hora_mexico()
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
                "fecha_hora": hora_mexico()
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
                "fecha_hora": hora_mexico()
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
                "fecha_hora": hora_mexico()
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
# --- SIMULADOR DE PRUEBAS ---
if __name__ == "__main__":
    # Número falso para no afectar tu base de datos real
    telefono_prueba = "+525599887766" 
    
    # NUEVO: Limpiamos la memoria de este número antes de empezar la prueba
    limpiar_estado(telefono_prueba)
    
    print("==============================================")
    print("🚀 SIMULADOR INTERACTIVO DE WHATSAPP 🚀")
    print("==============================================\n")
    print("Escribe 'salir' para terminar la prueba y cerrar el chat.\n")
    
    while True:
        # 1. El programa se pausa y espera a que tú escribas algo
        mensaje_usuario = input("👨‍🔧 Tú: ")
        
        # 2. Si escribes 'salir', rompemos el ciclo y terminamos
        if mensaje_usuario.lower() == 'salir':
            print("👋 Simulador terminado.")
            break
            
        # 3. Le pasamos tu mensaje al cerebro del bot y mostramos la respuesta
        respuesta_bot = procesar_mensaje_whatsapp(telefono_prueba, mensaje_usuario)
        print(f"🤖 Bot: {respuesta_bot}\n")