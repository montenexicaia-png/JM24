from database import supabase, bot_esta_activo, registrar_consumo_mensaje
from reportes import generar_matriz_semanal, generar_pdf_matriz_semanal
from avisos_datos import datos_faltantes, ESTADO_INCOMPLETO
import random
import datetime
import requests
import os
import pandas as pd
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
# Forzar la lectura de las contraseñas
load_dotenv()

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

def enviar_mensaje_whatsapp(telefono, mensaje):
    """Función clonada exactamente de server.py para enviar alertas automáticas"""
    # 1. Extraemos y limpiamos basura, espacios y comillas accidentales
    TOKEN = os.getenv("TOKEN_ACCESO_META", "").strip().strip('"').strip("'")
    PHONE_ID = os.getenv("PHONE_NUMBER_ID", "").strip().strip('"').strip("'")
    
    if not TOKEN or not PHONE_ID:
        print("❌ Error: No se encontraron las credenciales de Meta.")
        return

    # 2. Limpiamos el número quitando el '+' (igual que server.py)
    telefono_destino = telefono.strip().lstrip("+")
    
    # 3. Usamos la API v19.0 exacta
    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "text",
        "text": {"body": mensaje}
    }
    
    try:
        respuesta = requests.post(url, json=payload, headers=headers)
        if respuesta.status_code in [200, 201]:
            print(f"✅ Mensaje automático enviado exitosamente a {telefono_destino}")
        else:
            print(f"⚠️ Error de Meta al enviar a {telefono_destino}: {respuesta.text}")
    except Exception as e:
        print(f"❌ Error de conexión al enviar WhatsApp: {e}")

def enviar_imagen_whatsapp(telefono, url_imagen, caption=""):
    """Envía una imagen que ya está alojada en una URL pública (ej. fotos_obra de Supabase)."""
    TOKEN = os.getenv("TOKEN_ACCESO_META", "").strip().strip('"').strip("'")
    PHONE_ID = os.getenv("PHONE_NUMBER_ID", "").strip().strip('"').strip("'")

    if not TOKEN or not PHONE_ID:
        print("❌ Error: No se encontraron las credenciales de Meta.")
        return

    telefono_destino = telefono.strip().lstrip("+")
    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "image",
        "image": {"link": url_imagen, "caption": caption}
    }

    try:
        respuesta = requests.post(url, json=payload, headers=headers)
        if respuesta.status_code in [200, 201]:
            print(f"✅ Imagen enviada exitosamente a {telefono_destino}")
        else:
            print(f"⚠️ Error de Meta al enviar imagen a {telefono_destino}: {respuesta.text}")
    except Exception as e:
        print(f"❌ Error de conexión al enviar imagen WhatsApp: {e}")

def enviar_plantilla_whatsapp(telefono, nombre_plantilla, variable_texto):
    """Envía una plantilla oficial de Meta aprobada con 1 variable en el cuerpo."""
    TOKEN = os.getenv("TOKEN_ACCESO_META", "").strip().strip('"').strip("'")
    PHONE_ID = os.getenv("PHONE_NUMBER_ID", "").strip().strip('"').strip("'")
    
    url = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Estructura estricta que exige Meta para las plantillas
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {
                "code": "es_MX" # Código del idioma que elegimos
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": variable_texto  # Aquí se inyectará "la mañana" o "la tarde"
                        }
                    ]
                }
            ]
        }
    }
    
    try:
        respuesta = requests.post(url, headers=headers, json=payload)
        print(f"Respuesta Plantilla Meta para {telefono}: {respuesta.status_code} - {respuesta.text}")
    except Exception as e:
        print(f"Error enviando plantilla a {telefono}: {e}")

def enviar_documento_whatsapp_plantilla(telefono, nombre_plantilla, pdf_bytes, nombre_archivo, variable_texto):
    """
    Manda un documento REAL adjunto por WhatsApp usando una plantilla con encabezado tipo
    Documento (necesaria porque es un mensaje iniciado por el bot, fuera de la ventana de 24h).
    Requiere que 'nombre_plantilla' ya esté aprobada en Meta Business Manager con un header
    tipo Documento y 1 variable de texto en el body.
    """
    TOKEN = os.getenv("TOKEN_ACCESO_META", "").strip().strip('"').strip("'")
    PHONE_ID = os.getenv("PHONE_NUMBER_ID", "").strip().strip('"').strip("'")

    if not TOKEN or not PHONE_ID:
        print("❌ Error: No se encontraron las credenciales de Meta.")
        return False

    # 1. Subimos el PDF a los servidores de Meta para obtener un media_id
    url_media = f"https://graph.facebook.com/v22.0/{PHONE_ID}/media"
    headers_media = {"Authorization": f"Bearer {TOKEN}"}
    archivos = {
        "file": (nombre_archivo, pdf_bytes, "application/pdf"),
        "messaging_product": (None, "whatsapp"),
        "type": (None, "application/pdf"),
    }

    try:
        resp_media = requests.post(url_media, headers=headers_media, files=archivos)
        media_id = resp_media.json().get("id")
        if not media_id:
            print(f"❌ Meta no devolvió un media_id al subir el PDF: {resp_media.text}")
            return False
    except Exception as e:
        print(f"❌ Error al subir el PDF a Meta: {e}")
        return False

    # 2. Enviamos la plantilla con el documento ya subido como header
    url_msg = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"
    headers_msg = {
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
                {
                    "type": "header",
                    "parameters": [
                        {"type": "document", "document": {"id": media_id, "filename": nombre_archivo}}
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "parameter_name": "rango_fechas", "text": variable_texto}
                    ]
                }
            ]
        }
    }

    try:
        respuesta = requests.post(url_msg, headers=headers_msg, json=payload)
        print(f"Respuesta plantilla de documento para {telefono}: {respuesta.status_code} - {respuesta.text}")
        return respuesta.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Error enviando el documento por plantilla a {telefono}: {e}")
        return False

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

# ==========================================
# 📝 COMPLETAR DATOS (trabajadores cargados desde una lista con estado INCOMPLETO)
# Pregunta SOLO lo que les falta y ACTUALIZA su registro existente (no inserta uno nuevo).
# Al confirmar pasan a PENDIENTE para que RH los apruebe desde la Sala de Espera.
# ==========================================
RANGOS_DISPONIBLES = {"1": "Cabo", "2": "Oficial", "3": "Medio", "4": "Ayudante"}
DATO_POR_ESTADO = {
    "COMPLETAR_PUESTO": "puesto",
    "COMPLETAR_RANGO": "rango",
    "COMPLETAR_OBRA": "obra",
    "COMPLETAR_FOTO": "foto",
}

def _preguntar_dato_faltante(telefono: str, datos_temp: dict) -> str:
    """Pregunta el siguiente dato de datos_temp['faltan']; si ya no queda ninguno, pide la confirmación."""
    faltan = datos_temp.get("faltan", [])

    if not faltan:
        guardar_estado(telefono, "COMPLETAR_CONFIRMACION", datos_temp)
        nuevos = datos_temp.get("nuevos", {})
        resumen = f"👤 *Nombre:* {datos_temp.get('nombre', '')}\n"
        if "rol" in nuevos:
            resumen += f"👷‍♂️ *Puesto:* {nuevos['rol']}\n"
        if "rango" in nuevos:
            resumen += f"🎖️ *Rango:* {nuevos['rango']}\n"
        if "obra_actual" in nuevos:
            resumen += f"🏗️ *Obra:* {nuevos['obra_actual']}\n"
        if "foto_perfil_url" in nuevos:
            resumen += "📸 *Foto:* ✅ Recibida\n"
        return (f"📝 Por favor revisa que tus datos sean correctos:\n\n{resumen}\n"
                f"¿Todo está bien? (Responde con el NÚMERO):\n"
                f"1️⃣ Sí, enviar solicitud\n"
                f"2️⃣ No, empezar de nuevo")

    dato = faltan[0]

    if dato == "puesto":
        mapeo_roles = {str(i): rol for i, rol in enumerate(obtener_roles_dinamicos(), start=1)}
        datos_temp["mapeo_roles"] = mapeo_roles
        guardar_estado(telefono, "COMPLETAR_PUESTO", datos_temp)
        menu = "".join(f"{i}️⃣ {rol}\n" for i, rol in mapeo_roles.items())
        return f"👷‍♂️ Selecciona tu *Puesto* respondiendo con el *NÚMERO* correspondiente:\n\n{menu}"

    if dato == "rango":
        guardar_estado(telefono, "COMPLETAR_RANGO", datos_temp)
        menu = "".join(f"{i}️⃣ {rango}\n" for i, rango in RANGOS_DISPONIBLES.items())
        return f"🎖️ Selecciona tu *Rango* respondiendo con el *NÚMERO* correspondiente:\n\n{menu}"

    if dato == "obra":
        try:
            res_obras = supabase.table("catalogo_obras").select("nombre").eq("estado", "ACTIVA").execute()
            obras_activas = [o["nombre"] for o in res_obras.data] if res_obras.data else []
        except Exception:
            obras_activas = []

        if not obras_activas:
            # Sin obras en el catálogo no hay nada que elegir: saltamos el paso y RH la asigna después
            datos_temp["faltan"] = faltan[1:]
            return _preguntar_dato_faltante(telefono, datos_temp)

        mapeo_obras = {str(i): obra for i, obra in enumerate(obras_activas, start=1)}
        datos_temp["mapeo_obras"] = mapeo_obras
        guardar_estado(telefono, "COMPLETAR_OBRA", datos_temp)
        menu = "".join(f"{i}️⃣ {obra}\n" for i, obra in mapeo_obras.items())
        return f"🏗️ ¿A qué obra fuiste asignado? (Responde con el *NÚMERO*):\n\n{menu}"

    # dato == "foto"
    guardar_estado(telefono, "COMPLETAR_FOTO", datos_temp)
    return ("📸 Envíame una *Foto de perfil* tuya (tipo credencial o selfie) "
            "para terminar tu registro.")


def procesar_completar_datos(empleado: dict, telefono: str, texto_recibido: str,
                             estado_actual: str, datos_temp: dict) -> str:
    """Conversación para que un empleado INCOMPLETO complete sus datos. Devuelve el mensaje de respuesta."""
    nombre = empleado["nombre_completo"]
    opcion = texto_recibido.strip()

    # --- Primer mensaje (o estado ajeno a este flujo): calculamos qué le falta y arrancamos ---
    if not estado_actual or not estado_actual.startswith("COMPLETAR_"):
        faltan = datos_faltantes(empleado)
        if not faltan:
            # Ya tenía todo: no hay nada que preguntar, solo lo mandamos a revisión
            supabase.table("empleados").update({"estado": "PENDIENTE"}).eq("empleado_id", empleado["empleado_id"]).execute()
            limpiar_estado(telefono)
            return ("✅ *¡Tus datos están completos!*\n\n"
                    "Tu perfil pasó a la ⏳ *Sala de Espera*. Por favor, espera a que el administrador apruebe tu acceso.")

        datos_temp = {"nombre": nombre, "faltan": faltan, "nuevos": {}}
        nombres_datos = {"puesto": "puesto", "rango": "rango", "obra": "obra", "foto": "foto de perfil"}
        lista = ", ".join(nombres_datos[d] for d in faltan)
        intro = (f"👋 ¡Hola, {nombre.split()[0].title()}! Ya estás en la lista de personal de la obra 🏗️, "
                 f"pero para terminar tu registro me falta: *{lista}*.\n\nVamos paso a paso.\n\n")
        return intro + _preguntar_dato_faltante(telefono, datos_temp)

    nuevos = datos_temp.setdefault("nuevos", {})

    # --- Confirmación final ---
    if estado_actual == "COMPLETAR_CONFIRMACION":
        if opcion == "1":
            actualizacion = dict(nuevos)
            actualizacion["estado"] = "PENDIENTE"
            try:
                supabase.table("empleados").update(actualizacion).eq("empleado_id", empleado["empleado_id"]).execute()
                limpiar_estado(telefono)
                return ("✅ *¡Solicitud enviada con éxito!*\n\n"
                        "Tu perfil ha sido guardado y enviado a la ⏳ *Sala de Espera*.\n"
                        "Por favor, espera a que el administrador apruebe tu acceso. Te avisaremos cuando puedas comenzar a registrar tus asistencias.")
            except Exception as e:
                return f"❌ Hubo un error al guardar tus datos: {str(e)}"

        if opcion == "2":
            datos_temp = {"nombre": nombre, "faltan": datos_faltantes(empleado), "nuevos": {}}
            return "🔄 Reiniciando...\n\n" + _preguntar_dato_faltante(telefono, datos_temp)

        return "⚠️ Opción no válida. Responde con *1* (Sí, enviar) o *2* (No, empezar de nuevo)."

    # --- Respuesta al dato que se estaba preguntando ---
    if estado_actual == "COMPLETAR_PUESTO":
        mapeo_roles = datos_temp.get("mapeo_roles", {})
        if opcion not in mapeo_roles:
            return "⚠️ Opción no válida. Por favor, responde únicamente con el *NÚMERO* de la lista."
        nuevos["rol"] = mapeo_roles[opcion]

    elif estado_actual == "COMPLETAR_RANGO":
        if opcion not in RANGOS_DISPONIBLES:
            return "⚠️ Opción no válida. Por favor, responde con un NÚMERO del 1 al 4."
        nuevos["rango"] = RANGOS_DISPONIBLES[opcion]

    elif estado_actual == "COMPLETAR_OBRA":
        mapeo_obras = datos_temp.get("mapeo_obras", {})
        if opcion not in mapeo_obras:
            return "⚠️ Opción no válida. Por favor, responde únicamente con el *NÚMERO* de la lista."
        nuevos["obra_actual"] = mapeo_obras[opcion]

    elif estado_actual == "COMPLETAR_FOTO":
        if not texto_recibido.startswith("FOTO|"):
            return "⚠️ Por favor, usa la cámara o galería de WhatsApp 📷 para enviar tu *Foto de perfil*."
        nuevos["foto_perfil_url"] = texto_recibido.split("|")[1]

    else:
        # Estado COMPLETAR_ desconocido: lo reiniciamos desde cero
        limpiar_estado(telefono)
        return procesar_completar_datos(empleado, telefono, texto_recibido, None, {})

    dato_respondido = DATO_POR_ESTADO[estado_actual]
    datos_temp["faltan"] = [d for d in datos_temp.get("faltan", []) if d != dato_respondido]
    return _preguntar_dato_faltante(telefono, datos_temp)


# --- CEREBRO PRINCIPAL ---
def procesar_mensaje_whatsapp(telefono: str, texto_recibido: str) -> str:
    texto = texto_recibido.strip().upper()
    
    # 1. LEEMOS LA MEMORIA PRIMERO (Para saber si ya estábamos platicando)
    memoria = obtener_estado(telefono)
    estado_actual = memoria["estado"] if memoria else None
    datos_temp = memoria["datos_temporales"] if memoria else {}

    # ==========================================
    # 🔔 FLUJO VIP: El Jefe dispara las alertas oficiales
    # Lo ponemos aquí arriba para que se salte el filtro de empleados
    # ==========================================
    if texto == "AVISAR":
        # Verificamos que quien escribe esté autorizado (dentro de telefono_encargado en Supabase)
        try:
            res_config = supabase.table("configuracion").select("telefono_encargado").eq("id", 1).execute()
            cadena_telefonos = res_config.data[0].get("telefono_encargado", "") if res_config.data else ""
            telefonos_autorizados = [tel.strip() for tel in cadena_telefonos.split(",") if tel.strip()]
        except Exception as e:
            print(f"❌ Error verificando autorización de AVISAR: {e}")
            telefonos_autorizados = []
        
        if telefono not in telefonos_autorizados:
            print(f"🚫 Intento de AVISAR no autorizado desde {telefono}")
            return "⛔ No tienes autorización para ejecutar este comando."
        
        # 1. Le confirmamos al jefe que recibimos la orden
        enviar_mensaje_whatsapp(telefono, "⏳ Procesando lista de asistencia en tiempo real. Disparando plantillas oficiales de Meta, por favor espera...")
        
        # 2. Ejecutamos nuestra nueva función de disparo masivo (que revisa en vivo quién falta)
        disparar_avisos_rezagados(telefono)
        
        # 3. Limpiamos el estado del jefe
        limpiar_estado(telefono)
        
        return "✅ Escaneo y envío de avisos finalizado."
    # ==========================================

    # ==========================================
    # 📊 COMANDO: Reporte de cuadrilla (Encargado/Director)
    # Igual que AVISAR, se revisa antes de la máquina de estados para que
    # funcione sin importar en qué paso de su propio turno esté el Encargado.
    # ==========================================
    if texto == "MI CUADRILLA":
        try:
            res_quien = supabase.table("empleados").select("*").eq("telefono", telefono).execute()
            quien_pregunta = res_quien.data[0] if res_quien.data else None
        except Exception as e:
            return f"⚠️ Error de conexión: {str(e)}"

        if not quien_pregunta or quien_pregunta.get("jerarquia") not in ("ENCARGADO", "DIRECTOR"):
            return "⛔ No tienes autorización para usar este comando."

        texto_reporte, fotos = generar_reporte_cuadrilla(quien_pregunta)
        enviar_mensaje_whatsapp(telefono, texto_reporte)
        registrar_consumo_mensaje()

        for nombre_trabajador, url_foto in fotos:
            if url_foto and str(url_foto).startswith("http"):
                enviar_imagen_whatsapp(telefono, url_foto, caption=f"📸 {nombre_trabajador}")
                registrar_consumo_mensaje()

        return None
    # ==========================================

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
            elif empleado["estado"] == ESTADO_INCOMPLETO:
                return procesar_completar_datos(empleado, telefono, texto_recibido, estado_actual, datos_temp)
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
                    "obra": empleado.get("obra_actual", "Sin Obra"),  # <-- NUEVO: Sellamos la obra
                    "tipo_registro": "ENTRADA",
                    "latitud": lat,
                    "longitud": lon,
                    "ubicacion": enlace_mapas, 
                    "foto_url": url_real,
                    "fecha_hora": hora_mexico()
                }).execute()
                guardar_estado(telefono, "EN_TURNO", {"empleado_id": empleado['empleado_id']})
                return f"✅ ¡Tu ENTRADA quedó registrada oficialmente, {empleado['nombre_completo']}! Ya estás en turno."
            except Exception as e:
                return f"❌ Error: {str(e)}"
        else:
            return "⚠️ Por favor, usa la cámara de WhatsApp 📷 para enviar la *Foto*."

    # === FLUJO DE AVISOS (REPORTE NORMAL) ===
    # ✅ CORRECTO
    elif estado_actual == "ESPERANDO_AVISO":
        try:
            supabase.table("reportes_incidentes").insert({
                "empleado_id": empleado['empleado_id'],
                "obra": empleado.get("obra_actual", "Sin Obra"),
                "descripcion": texto_recibido.strip(), 
                "estado": "AVISO",
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
                "obra": empleado.get("obra_actual", "Sin Obra"),  # <-- NUEVO
                "descripcion": texto_recibido.strip(),
                "estado": "URGENTE", 
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
                "obra": empleado.get("obra_actual", "Sin Obra"),  # <-- NUEVO
                "tipo_registro": "SALIDA",
                "latitud": lat_salida,
                "longitud": lon_salida,
                "ubicacion": enlace_mapas, 
                "foto_url": datos_temp.get("url_foto_salida"),
                "avances": datos_temp.get("avances"),
                "pendientes": texto_recibido.strip(),
                "fecha_hora": hora_mexico()
            }).execute()
            
            # Turno terminado, limpiamos la memoria para que mañana empiece de cero
            limpiar_estado(telefono)
            return "🌙 ¡Bitácora completada y enviada al contratista! Tu SALIDA oficial ha sido registrada. ¡Buen descanso!"
        except Exception as e:
            return f"❌ Error al guardar tu salida: {str(e)}"   

        # === MENSAJE POR DEFECTO (ESTADO DESCONOCIDO O CORRUPTO) ===
    else:
        instrucciones_por_estado = {
            "ESPERANDO_UBICACION": "compartas tu 📍 Ubicación (usa el clip de WhatsApp)",
            "ESPERANDO_FOTO_ENTRADA": "envíes tu 📸 Foto (usa la cámara de WhatsApp)",
            "ESPERANDO_UBICACION_SALIDA": "compartas tu 📍 Ubicación de salida",
            "ESPERANDO_FOTO_SALIDA": "envíes tu 📸 Foto de salida",
            "ESPERANDO_AVANCES": "me cuentes los avances del día",
            "ESPERANDO_PENDIENTES": "me cuentes los pendientes de mañana",
            "ESPERANDO_AVISO": "escribas el reporte o novedad",
            "ESPERANDO_URGENCIA": "describas el problema urgente",
        }

        if estado_actual in instrucciones_por_estado:
            return f"🤖 {empleado['nombre_completo']}, todavía necesito que {instrucciones_por_estado[estado_actual]}."
        else:
            print(f"⚠️ Estado desconocido '{estado_actual}' para {telefono}. Reiniciando su conversación.")
            limpiar_estado(telefono)
            return (f"🤖 Hola de nuevo, {empleado['nombre_completo']}. Tu conversación se había quedado "
                    f"en un punto raro, así que la reinicié. Escribe *1* para registrar tu ENTRADA.")



# ==========================================
# 📊 REPORTE DE CUADRILLA (Encargado / Director)
# ==========================================

def generar_reporte_cuadrilla(empleado: dict):
    """
    Arma el reporte de HOY (presentes/faltantes/incidentes urgentes) para la cuadrilla de un
    Encargado (empleados con supervisor_id == su empleado_id), o para toda la operación activa
    si quien pregunta es Director. Devuelve (texto_resumen, lista_de_fotos_presentes).
    """
    try:
        ahora = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
        hoy = ahora.strftime("%Y-%m-%d")
        inicio_dia = f"{hoy}T00:00:00"
        fin_dia = f"{hoy}T23:59:59"

        if empleado.get("jerarquia") == "DIRECTOR":
            res_equipo = supabase.table("empleados").select("empleado_id, nombre_completo") \
                .eq("estado", "ACTIVO").neq("jerarquia", "DIRECTOR").execute()
            titulo_grupo = "de TODA la operación"
        else:
            res_equipo = supabase.table("empleados").select("empleado_id, nombre_completo") \
                .eq("estado", "ACTIVO").eq("supervisor_id", empleado["empleado_id"]).execute()
            titulo_grupo = "de tu cuadrilla"

        equipo = res_equipo.data or []
        if not equipo:
            return (
                f"ℹ️ Todavía no tienes trabajadores asignados {titulo_grupo}. "
                f"Pide al administrador que te asigne tu cuadrilla desde el panel.",
                []
            )

        ids_equipo = [e["empleado_id"] for e in equipo]
        nombres_por_id = {e["empleado_id"]: e["nombre_completo"] for e in equipo}

        res_entradas = supabase.table("registros_asistencia").select("empleado_id, foto_url") \
            .eq("tipo_registro", "ENTRADA").in_("empleado_id", ids_equipo) \
            .gte("fecha_hora", inicio_dia).lte("fecha_hora", fin_dia).execute()
        entradas_hoy = res_entradas.data or []
        ids_presentes = {e["empleado_id"] for e in entradas_hoy}

        res_urgentes = supabase.table("reportes_incidentes").select("empleado_id, descripcion") \
            .eq("estado", "URGENTE").in_("empleado_id", ids_equipo) \
            .gte("fecha_hora", inicio_dia).lte("fecha_hora", fin_dia).execute()
        urgentes_hoy = res_urgentes.data or []

        presentes = [nombres_por_id[eid] for eid in ids_presentes]
        faltantes = [nombres_por_id[eid] for eid in ids_equipo if eid not in ids_presentes]

        texto = f"📊 *Reporte {titulo_grupo}* — {ahora.strftime('%d/%m/%Y %H:%M')}\n\n"
        texto += f"🟢 *Presentes ({len(presentes)}):*\n"
        texto += "\n".join(f"• {n}" for n in presentes) if presentes else "Nadie ha registrado entrada todavía."
        texto += f"\n\n🔴 *Faltantes ({len(faltantes)}):*\n"
        texto += "\n".join(f"• {n}" for n in faltantes) if faltantes else "¡Nadie falta!"

        if urgentes_hoy:
            texto += f"\n\n🚨 *Incidentes urgentes hoy ({len(urgentes_hoy)}):*\n"
            texto += "\n".join(f"• {nombres_por_id.get(inc['empleado_id'], 'Desconocido')}: {inc['descripcion']}" for inc in urgentes_hoy)

        # dict en vez de lista para no repetir foto si alguien tiene más de un registro de ENTRADA hoy
        fotos_por_id = {}
        for e in entradas_hoy:
            if e.get("foto_url") and e["empleado_id"] not in fotos_por_id:
                fotos_por_id[e["empleado_id"]] = e["foto_url"]
        fotos = [(nombres_por_id[eid], url) for eid, url in fotos_por_id.items()]
        return (texto, fotos)
    except Exception as e:
        return (f"❌ Error al generar el reporte de tu cuadrilla: {str(e)}", [])


# ==========================================
# ⏰ SISTEMA DE ALARMA AUTOMÁTICO
# ==========================================

def disparar_avisos_rezagados(telefono_jefe):
    """Busca quién falta en el momento exacto de la autorización y dispara las plantillas"""
    try:
        # 1. Determinar si es corte de ENTRADA o SALIDA según la hora actual
        ahora = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
        hora_actual = ahora.hour
        
        if hora_actual < 14: # Si es antes de las 2 PM
            tipo_corte = "ENTRADA"
            variable_texto = "entrada"
        else: # Si es en la tarde/noche
            tipo_corte = "SALIDA"
            variable_texto = "salida"

        hoy = ahora.strftime("%Y-%m-%d")
        inicio_dia = f"{hoy}T00:00:00"
        fin_dia = f"{hoy}T23:59:59"
        
        # 2. Buscar a todos los empleados ACTIVOS
        res_empleados = supabase.table("empleados").select("empleado_id, telefono, nombre_completo").eq("estado", "ACTIVO").execute()
        empleados_activos = res_empleados.data
        if not empleados_activos: return
        
        # 3. Buscar a los que YA registraron hoy
        res_registros = supabase.table("registros_asistencia") \
            .select("empleado_id") \
            .eq("tipo_registro", tipo_corte) \
            .gte("fecha_hora", inicio_dia) \
            .lte("fecha_hora", fin_dia) \
            .execute()
            
        ids_registrados = [reg["empleado_id"] for reg in res_registros.data]
        
        # 4. Filtrar a los FALTANTES
        # Sin teléfono no hay a quién avisar (y el jefe vería en su resumen a alguien que nunca recibió el mensaje)
        faltantes = [emp for emp in empleados_activos
                     if emp["empleado_id"] not in ids_registrados and (emp.get("telefono") or "").strip()]
        
        # 5. Enviar mensajes a los rezagados
        if len(faltantes) > 0:
            print(f"🔔 Disparando {len(faltantes)} plantillas de {tipo_corte} a rezagados...")
            nombres_faltantes = []
            for emp in faltantes:
                # Disparamos la plantilla oficial de Meta a cada trabajador
                enviar_plantilla_whatsapp(emp["telefono"], "recordatorio_asistencia_pendiente", variable_texto)
                nombres_faltantes.append(emp["nombre_completo"])
            
            # 6. Confirmarle al jefe (Como el jefe acaba de escribir "AVISAR", la ventana de 24h de Meta está abierta y podemos usar texto normal)
            nombres_str = ", ".join(nombres_faltantes)
            mensaje_jefe = f"✅ *Avisos Enviados*\nSe disparó el recordatorio de {tipo_corte} a {len(faltantes)} trabajadores:\n{nombres_str}"
            enviar_mensaje_whatsapp(telefono_jefe, mensaje_jefe)
        else:
            enviar_mensaje_whatsapp(telefono_jefe, f"✅ Todos los trabajadores han registrado su {tipo_corte} de hoy. No hay rezagados.")
            
    except Exception as e:
        print(f"❌ Error al disparar avisos: {e}")

# Variables globales para que el bot no dispare dos veces el mismo aviso en el mismo minuto
ultimo_aviso_entrada = None
ultimo_aviso_salida = None

def checar_reloj_bot():
    global ultimo_aviso_entrada, ultimo_aviso_salida

    try:
        # --- Bot Matrix Panel: si está suspendido, no se disparan recordatorios automáticos ---
        if not bot_esta_activo():
            return

        # 1. Hora exacta en México
        ahora = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
        hora_actual = ahora.strftime("%H:%M")
        fecha_actual = ahora.strftime("%Y-%m-%d")
        
        # 2. Consultamos la configuración en Supabase
        res_config = supabase.table("configuracion").select("*").eq("id", 1).execute()
        if not res_config.data:
            print("⚠️ [RELOJ] Advertencia: No se encontró la fila con id=1 en la tabla 'configuracion'.")
            return
            
        config = res_config.data[0]
        
        # Usamos tus nombres de columnas exactos
        hora_entrada = config.get("hora_corte_entrada", "08:30")
        hora_salida = config.get("hora_corte_salida", "17:30")
        
        # Soportar múltiples encargados separados por comas
        cadena_telefonos = config.get("telefono_encargado", "")
        telefonos_jefes = [tel.strip() for tel in cadena_telefonos.split(",") if tel.strip()]
        
        if not telefonos_jefes:
            print("⚠️ [RELOJ] El campo 'telefono_encargado' en Supabase está vacío. No hay a quién alertar.")
            return
        
        # 3. Disparo de ENTRADA
        if hora_actual == hora_entrada and ultimo_aviso_entrada != fecha_actual:
            ultimo_aviso_entrada = fecha_actual
            print(f"⏰ [RELOJ] ¡Hora de ENTRADA ({hora_entrada})! Enviando plantilla al jefe...")
            for tel in telefonos_jefes:
                enviar_plantilla_whatsapp(tel, "alerta_corte_asistencia", "la mañana")
            
        # 4. Disparo de SALIDA
        if hora_actual == hora_salida and ultimo_aviso_salida != fecha_actual:
            ultimo_aviso_salida = fecha_actual
            print(f"⏰ [RELOJ] ¡Hora de SALIDA ({hora_salida})! Enviando plantilla al jefe...")
            for tel in telefonos_jefes:
                enviar_plantilla_whatsapp(tel, "alerta_corte_asistencia", "la tarde")
            
    except Exception as e:
        print(f"❌ [ERROR EN RELOJ AUTOMÁTICO]: {e}")

# ==========================================
# 📄 REPORTE PDF SEMANAL AUTOMÁTICO AL DIRECTOR
# ==========================================

def disparar_reporte_semanal_director():
    """
    Arma el PDF de asistencia semanal (todas las obras, nombres en vez de ID) y se lo manda
    como documento adjunto real por WhatsApp a cada empleado con jerarquia='DIRECTOR'.
    Requiere la plantilla 'reporte_semanal_director' (header tipo Documento) ya aprobada en Meta.
    """
    try:
        if not bot_esta_activo():
            return

        hoy = datetime.date.today()
        lunes = hoy - datetime.timedelta(days=hoy.weekday())
        inicio_semana = f"{lunes.isoformat()}T00:00:00"
        fin_semana = f"{hoy.isoformat()}T23:59:59"

        res_directores = supabase.table("empleados").select("telefono, nombre_completo") \
            .eq("estado", "ACTIVO").eq("jerarquia", "DIRECTOR").execute()
        directores = res_directores.data or []
        if not directores:
            print("ℹ️ [REPORTE SEMANAL] No hay ningún Director configurado en la jerarquía. Nada que enviar.")
            return

        res_empleados = supabase.table("empleados").select("*").execute()
        res_asistencias = supabase.table("registros_asistencia").select("*") \
            .gte("fecha_hora", inicio_semana).lte("fecha_hora", fin_semana).execute()

        df_empleados = pd.DataFrame(res_empleados.data or [])
        df_asistencias = pd.DataFrame(res_asistencias.data or [])
        if df_empleados.empty or df_asistencias.empty:
            print("ℹ️ [REPORTE SEMANAL] Sin datos suficientes para armar el reporte de esta semana.")
            return

        df_asistencias["fecha_dt"] = pd.to_datetime(df_asistencias["fecha_hora"])
        try:
            df_asistencias["fecha_dt"] = df_asistencias["fecha_dt"].dt.tz_convert("America/Mexico_City")
        except TypeError:
            df_asistencias["fecha_dt"] = df_asistencias["fecha_dt"].dt.tz_localize("UTC").dt.tz_convert("America/Mexico_City")

        df_matriz, fechas_cabecera = generar_matriz_semanal(hoy, df_empleados, df_asistencias)
        if df_matriz.empty:
            print("ℹ️ [REPORTE SEMANAL] No hay empleados activos para incluir en la matriz.")
            return

        res_config = supabase.table("configuracion").select("empresa_nombre, empresa_logo, color_sidebar").eq("id", 1).execute()
        config = res_config.data[0] if res_config.data else {}

        pdf_bytes = generar_pdf_matriz_semanal(
            df_matriz, fechas_cabecera,
            empresa_nombre=config.get("empresa_nombre") or "Centro de Mando",
            color_marca_hex=config.get("color_sidebar") or "#0E1C36",
            logo_url=config.get("empresa_logo") or ""
        )

        nombre_archivo = f"Reporte_Semanal_{lunes.strftime('%Y-%m-%d')}.pdf"
        rango_texto = f"{fechas_cabecera[0]} al {fechas_cabecera[-1]}"

        for director in directores:
            enviado = enviar_documento_whatsapp_plantilla(
                director["telefono"], "reporte_semanal_director", pdf_bytes, nombre_archivo, rango_texto
            )
            if enviado:
                print(f"✅ [REPORTE SEMANAL] Enviado a {director['nombre_completo']}")
            else:
                print(f"⚠️ [REPORTE SEMANAL] No se pudo enviar a {director['nombre_completo']}")

    except Exception as e:
        print(f"❌ [ERROR EN REPORTE SEMANAL DEL DIRECTOR]: {e}")

# Semana ISO (año-semana) de la última vez que se mandó el reporte, para no repetirlo
# si el minuto configurado coincide más de una vez (ej. al reiniciar el servicio)
ultima_semana_reporte_enviado = None

def checar_reporte_semanal_bot():
    """Cada minuto revisa si ya es el día/hora configurados en 'configuracion' para
    disparar el reporte semanal del Director (configurable desde el panel, igual que
    los horarios de entrada/salida)."""
    global ultima_semana_reporte_enviado

    try:
        if not bot_esta_activo():
            return

        ahora = datetime.datetime.now(ZoneInfo("America/Mexico_City"))
        hora_actual = ahora.strftime("%H:%M")
        semana_actual = ahora.strftime("%G-W%V")  # ej. "2026-W40", única por semana ISO

        res_config = supabase.table("configuracion").select("dia_reporte_semanal, hora_reporte_semanal").eq("id", 1).execute()
        if not res_config.data:
            return
        config = res_config.data[0]

        dia_configurado = config.get("dia_reporte_semanal")
        dia_configurado = 4 if dia_configurado is None else int(dia_configurado)  # 4 = Viernes
        hora_configurada = config.get("hora_reporte_semanal") or "11:00"

        if ahora.weekday() == dia_configurado and hora_actual == hora_configurada and ultima_semana_reporte_enviado != semana_actual:
            ultima_semana_reporte_enviado = semana_actual
            print(f"📄 [REPORTE SEMANAL] ¡Hora configurada ({hora_configurada})! Generando y enviando reporte al Director...")
            disparar_reporte_semanal_director()

    except Exception as e:
        print(f"❌ [ERROR AL CHECAR REPORTE SEMANAL]: {e}")

# ==========================================
# ⏰ ENCENDEMOS EL RELOJ EN SEGUNDO PLANO
# ==========================================
scheduler = BackgroundScheduler()
scheduler.add_job(checar_reloj_bot, 'interval', minutes=1)
scheduler.add_job(checar_reporte_semanal_bot, 'interval', minutes=1)
scheduler.start()

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